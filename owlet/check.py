import asyncio
import contextlib
import inspect
import json
import time
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Mapping,
    Sequence,
)
from dataclasses import dataclass, field, replace
from enum import StrEnum
from traceback import StackSummary, TracebackException
from typing import Any, Concatenate, cast, get_args, get_origin

import httpx

from owlet.config import ConfigError
from owlet.context import Context
from owlet.suggest import with_suggestion


class Status(StrEnum):
    PASS = "PASS"
    """The check passed."""
    WARN = "WARN"
    """Worth attention but not a failure, unless running in strict mode."""
    FAIL = "FAIL"
    """The check found a problem with the target."""
    SKIP = "SKIP"
    """The check wasn't performed on this target."""
    ERROR = "ERROR"
    """The check itself crashed or misbehaved, as opposed to finding a problem with the target."""


@dataclass(frozen=True)
class Result:
    """Represents the result of a check."""

    status: Status
    summary: str
    """One line saying what the check found. Anything longer goes in `details`."""
    name: str | None = None
    """Optional label for one of several results from the same check, e.g. a header name."""
    details: Sequence[str] = ()
    """Extra lines for people, e.g. each broken link. Printed indented under `summary`."""
    data: Mapping[str, Any] = field(default_factory=dict)
    """Values for scripts, e.g. {"days_left": 69}. Must be JSON-serializable; only shown in JSON output."""
    check_name: str = ""
    """Filled in by the runner with the name of the check that produced this result."""
    duration_seconds: float | None = None
    """Filled in by the runner with how long the check took. Every result from one check shares it."""
    traceback: str | None = None
    """Filled in by the runner on an ERROR result from an exception the check raised, to debug the check."""

    def __post_init__(self):
        try:
            status = Status(self.status)
        except ValueError:
            raise ValueError(f"Invalid result status {self.status!r}, expected one of {', '.join(Status)}.") from None
        object.__setattr__(self, "status", status)
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise TypeError(f"Result summary must be a non-empty string, got {self.summary!r}.")
        if self.summary.splitlines() != [self.summary]:
            raise ValueError(f"Result summary must be one line; put the rest in details: {self.summary!r}.")
        if isinstance(self.details, str) or not all(isinstance(line, str) for line in self.details):
            raise TypeError(f"Result details must be a list of strings, got {self.details!r}.")
        object.__setattr__(self, "details", tuple(self.details))
        # Fail inside the check, where it becomes an ERROR result, rather than when the JSON is printed.
        try:
            json.dumps(self.data, allow_nan=False)
        except (TypeError, ValueError) as e:
            raise TypeError(f"Result data must be JSON-serializable: {e}") from None
        object.__setattr__(self, "data", dict(self.data))

    @property
    def label(self) -> str:
        return f"{self.check_name} - {self.name}" if self.name else self.check_name


type CheckOutput = Result | Iterable[Result]
type CheckFunction = Callable[Concatenate[Context, ...], Awaitable[CheckOutput] | AsyncIterator[Result]]
"""An async function or async generator. Takes the Context positionally, plus any options as keyword-only parameters with defaults."""


@dataclass(frozen=True)
class Check:
    """Represents a single check."""

    name: str
    description: str | None
    func: CheckFunction
    options: Mapping[str, inspect.Parameter]
    """Configurable options, taken from the function's keyword-only parameters."""
    validate: Callable[..., None] | None = None
    """Called with every option as a keyword argument when the config loads; raises ConfigError for unusable values."""

    def resolve_options(self, values: Mapping[str, Any]) -> dict[str, Any]:
        """Validate options from the config against the function's signature. Unset options keep their defaults."""
        unknown = sorted(values.keys() - self.options.keys())
        if unknown:
            available = ", ".join(self.options) or "none"
            named = ", ".join(with_suggestion(key, self.options) for key in unknown)
            raise ConfigError(f"Unknown option(s) for check '{self.name}': {named}. Available: {available}.")
        resolved = {}
        for key, value in values.items():
            annotation = self.options[key].annotation
            try:
                resolved[key] = _coerce(value, annotation)
            except TypeError:
                raise ConfigError(f"Option '{self.name}.{key}' must be {_type_name(annotation)}, got {value!r}.") from None
        if self.validate:
            defaults = {name: param.default for name, param in self.options.items()}
            try:
                self.validate(**(defaults | resolved))
            except ConfigError as e:
                raise ConfigError(f"Check '{self.name}': {e}") from None
            except Exception as e:
                raise RuntimeError(f"Check '{self.name}': validate crashed with {_describe(e)}") from e
        return resolved

    async def run(self, ctx: Context, options: Mapping[str, Any], timeout: float | None = None) -> list[Result]:
        deadline = asyncio.timeout(timeout)
        started = time.perf_counter()
        # Filled in as the check produces results, so ones yielded before a crash or timeout are kept.
        results: list[Result] = []
        try:
            async with deadline:
                await self._collect(ctx, options, results)
            if not results:
                results.append(Result(Status.ERROR, "Check produced no results."))
        except Exception as e:  # noqa: BLE001 - a failing check must not abort the other checks
            if deadline.expired():
                results.append(Result(Status.FAIL, f"Timed out after {timeout:g}s."))
            elif _is_network_error(e):
                results.append(_text_result(Status.FAIL, _describe(e)))
            else:
                error = _text_result(Status.ERROR, _describe(e))
                results.append(replace(error, traceback=_check_traceback(e)))
        duration = time.perf_counter() - started
        return [replace(result, check_name=self.name, duration_seconds=duration) for result in results]

    async def _collect(self, ctx: Context, options: Mapping[str, Any], results: list[Result]) -> None:
        if inspect.isasyncgenfunction(self.func):
            async with contextlib.aclosing(self.func(ctx, **options)) as generator:
                async for result in generator:
                    results.append(_require_result(result))
        else:
            results.extend(_as_list(await cast(Awaitable[CheckOutput], self.func(ctx, **options))))


LOCAL_OS_ERRORS = (FileNotFoundError, FileExistsError, IsADirectoryError, NotADirectoryError, PermissionError)


def _is_network_error(e: Exception) -> bool:
    """Trouble reaching the target (DNS, refused or unreachable hosts, TLS errors, timeouts, malformed URLs): a problem with the site.

    Network failures surface as many OSError types, including plain OSError, so match those broadly but leave out
    filesystem errors, which point at a bug in the check and become ERROR instead.
    """
    if isinstance(e, (httpx.HTTPError, httpx.InvalidURL)):
        return True
    return isinstance(e, OSError) and not isinstance(e, LOCAL_OS_ERRORS)


def _check_traceback(e: Exception) -> str:
    """The traceback of an exception raised by a check, without the runner's own frames in this module."""
    exception = TracebackException.from_exception(e)
    exception.stack = StackSummary.from_list([frame for frame in exception.stack if frame.filename != __file__])
    return "".join(exception.format()).rstrip()


def _describe(e: Exception) -> str:
    return f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


def _text_result(status: Status, text: str) -> Result:
    """A Result from text we don't control, like an exception message: first line as summary, the rest as details."""
    summary, *details = [line for line in text.splitlines() if line.strip()] or ["(no message)"]
    return Result(status, summary, details=details)


def _coerce(value: Any, annotation: Any) -> Any:
    """Return `value` if it matches `annotation`, converting where TOML is looser (int for float); else raise TypeError."""
    if annotation is inspect.Parameter.empty or annotation is Any:
        return value
    if get_origin(annotation) is list:
        if not isinstance(value, list):
            raise TypeError
        (item_annotation,) = get_args(annotation) or (Any,)
        return [_coerce(item, item_annotation) for item in value]
    if not isinstance(annotation, type):
        return value  # Annotations we can't check (unions, literals, ...) are trusted.
    # bool is a subclass of int, but `true` for a number option is almost certainly a mistake.
    if isinstance(value, bool) and annotation is not bool:
        raise TypeError
    if annotation is float and isinstance(value, int):
        return float(value)
    if not isinstance(value, annotation):
        raise TypeError
    return value


def _type_name(annotation: Any) -> str:
    return annotation.__name__ if isinstance(annotation, type) else str(annotation)


def _as_list(output: Any) -> list[Result]:
    if isinstance(output, Result):
        return [output]
    if isinstance(output, str) or not isinstance(output, Iterable):
        raise TypeError(f"Check returned {type(output).__name__}, expected a Result or an iterable of Results.")
    return [_require_result(result) for result in output]


def _require_result(result: Any) -> Result:
    if not isinstance(result, Result):
        raise TypeError(f"Check produced {type(result).__name__}, expected Result.")
    return result


class Registry:
    """Holds checks by name."""

    def __init__(self) -> None:
        self._checks: dict[str, Check] = {}

    def check(self, func=None, *, validate: Callable[..., None] | None = None):
        """Register a check. Use as `@registry.check`, or as `@registry.check(validate=...)` to also validate option values."""

        def register(func):
            self.add(_make_check(func, validate))
            return func

        return register(func) if func else register

    def add(self, check: Check) -> None:
        if existing := self._checks.get(check.name):
            raise ValueError(
                f"Duplicate check name '{check.name}' in {check.func.__module__}, already defined in {existing.func.__module__}."
            )
        self._checks[check.name] = check

    @property
    def checks(self) -> dict[str, Check]:
        """A copy of the registered checks, in registration order."""
        return dict(self._checks)


registry = Registry()
"""The registry `@check` adds to, and that owlet.discover.discover_checks returns."""


def check(func=None, *, validate: Callable[..., None] | None = None):
    """Register a check in the default `registry`. Use as `@check`, or as `@check(validate=...)` to also validate option values."""
    return registry.check(func, validate=validate)


def _make_check(func, validate: Callable[..., None] | None) -> Check:
    if not (inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func)):
        raise TypeError(f"Check '{func.__name__}' must be an async function (async def).")
    options = _option_parameters(func)
    if validate:
        try:
            inspect.signature(validate).bind(**options)
        except TypeError:
            raise TypeError(f"Check '{func.__name__}': validate must take the options {', '.join(options)} as keywords.") from None
    return Check(func.__name__, inspect.getdoc(func), func, options, validate)


def _option_parameters(func) -> dict[str, inspect.Parameter]:
    """Every check takes the Context first; anything after it is an option and needs a default."""
    params = list(inspect.signature(func).parameters.values())
    ctx_param, option_params = (params[0], params[1:]) if params else (None, [])
    if ctx_param is None or ctx_param.kind not in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
        raise TypeError(f"Check '{func.__name__}' must take the Context as its first positional parameter.")
    for param in option_params:
        if param.kind is not inspect.Parameter.KEYWORD_ONLY or param.default is inspect.Parameter.empty:
            raise TypeError(f"Check '{func.__name__}': option '{param.name}' must be keyword-only with a default.")
    return {param.name: param for param in option_params}
