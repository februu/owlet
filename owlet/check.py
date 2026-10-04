import asyncio
import inspect
import pkgutil
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from importlib import import_module
from typing import Any

from owlet.context import Context


@dataclass(frozen=True)
class Result:
    """Represents the result of a check."""

    success : bool
    content : str | None = None
    name : str | None = None
    """Optional label for one of several results from the same check, e.g. a header name."""
    check_name : str = ""
    """Filled in by the runner with the name of the check that produced this result."""

    @property
    def label(self) -> str:
        return f"{self.check_name} - {self.name}" if self.name else self.check_name


type CheckOutput = Result | Iterable[Result]
type CheckFunction = Callable[[Context], Awaitable[CheckOutput] | AsyncIterator[Result] | CheckOutput]


@dataclass(frozen=True)
class Check:
    """Represents a single check."""

    name : str
    description : str | None
    func : CheckFunction

    async def run(self, ctx: Context) -> list[Result]:
        try:
            results = await self._collect(ctx)
        except Exception as e:  # noqa: BLE001 - a failing check must not abort the other checks
            message = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            results = [Result(False, message)]
        if not results:
            results = [Result(False, "Check produced no results.")]
        return [replace(result, check_name=self.name) for result in results]

    async def _collect(self, ctx: Context) -> list[Result]:
        if inspect.isasyncgenfunction(self.func):
            return _as_list([result async for result in self.func(ctx)])
        if inspect.iscoroutinefunction(self.func):
            return _as_list(await self.func(ctx))
        return await asyncio.to_thread(lambda: _as_list(self.func(ctx)))


def _as_list(output: Any) -> list[Result]:
    if isinstance(output, Result):
        return [output]
    if isinstance(output, str) or not isinstance(output, Iterable):
        raise TypeError(f"Check returned {type(output).__name__}, expected a Result or an iterable of Results.")
    results = list(output)
    for result in results:
        if not isinstance(result, Result):
            raise TypeError(f"Check produced {type(result).__name__}, expected Result.")
    return results


_registry: dict[str, Check] = {}


def check(func):
    if func.__name__ in _registry:
        raise ValueError(f"Duplicate check name '{func.__name__}'.")
    _registry[func.__name__] = Check(func.__name__, inspect.getdoc(func), func)
    return func


def discover_checks(package: str = "owlet.checks") -> dict[str, Check]:
    """Import every module in `package` so their @check decorators run, then return all registered checks."""
    for module_info in pkgutil.iter_modules(import_module(package).__path__):
        import_module(f"{package}.{module_info.name}")
    return dict(_registry)
