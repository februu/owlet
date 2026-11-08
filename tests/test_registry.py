"""Registering checks, and validating option values against their signatures."""

import inspect
from typing import Any

import pytest

from owlet.check import Check, Registry, Result, Status
from owlet.config import ConfigError
from owlet.discover import discover_checks


async def good(ctx, *, limit: int = 1, name: str = "x"):
    """Passes when it's good.

    More detail.
    """
    return Result(Status.PASS, "Fine.")


# Registering


def test_registering_reads_the_name_description_and_options():
    checks = Registry()
    checks.check(good)

    registered = checks.checks["good"]

    assert registered.name == "good"
    assert registered.description.startswith("Passes when it's good.")
    assert list(registered.options) == ["limit", "name"]
    assert registered.func is good


def test_both_decorator_forms_register_and_return_the_function():
    checks = Registry()

    @checks.check
    async def plain(ctx):
        pass

    def validate():
        pass

    @checks.check(validate=validate)
    async def with_validate(ctx):
        pass

    assert inspect.iscoroutinefunction(plain)
    assert inspect.iscoroutinefunction(with_validate)
    assert checks.checks["plain"].validate is None
    assert checks.checks["with_validate"].validate is validate


def test_async_generators_can_be_checks():
    checks = Registry()

    @checks.check
    async def generator(ctx):
        yield Result(Status.PASS, "Fine.")

    assert "generator" in checks.checks


def test_checks_keep_registration_order():
    checks = Registry()
    for name in ["zebra", "apple", "mango"]:

        async def func(ctx):
            pass

        func.__name__ = name
        checks.check(func)

    assert list(checks.checks) == ["zebra", "apple", "mango"]


def test_checks_property_is_a_copy():
    checks = Registry()
    checks.check(good)
    checks.checks.clear()
    assert "good" in checks.checks


def test_duplicate_name_is_rejected_naming_both_modules():
    checks = Registry()
    checks.check(good)
    with pytest.raises(ValueError, match=r"Duplicate check name 'good'.*already defined in"):
        checks.check(good)


async def _no_params():
    pass


async def _keyword_context(*, ctx):
    pass


async def _variadic_context(*ctx):
    pass


async def _positional_option(ctx, limit=1):
    pass


async def _option_without_default(ctx, *, limit):
    pass


async def _variadic_args(ctx, *args):
    pass


async def _variadic_kwargs(ctx, **kwargs):
    pass


async def _reserved_option(ctx, *, timeout_seconds=1):
    pass


def _not_async(ctx):
    pass


@pytest.mark.parametrize(
    ("func", "message"),
    [
        (_not_async, "must be an async function"),
        (_no_params, "must take the Context"),
        (_keyword_context, "must take the Context"),
        (_variadic_context, "must take the Context"),
        (_positional_option, "'limit' must be keyword-only with a default"),
        (_option_without_default, "'limit' must be keyword-only with a default"),
        (_variadic_args, "'args' must be keyword-only with a default"),
        (_variadic_kwargs, "'kwargs' must be keyword-only with a default"),
        (_reserved_option, "'timeout_seconds' is reserved"),
    ],
    ids=lambda value: value.__name__.strip("_") if callable(value) else "",
)
def test_invalid_signature_is_rejected_when_registering(func, message):
    with pytest.raises(TypeError, match=message):
        Registry().check(func)


def _validate_wrong_name(*, other):
    pass


def _validate_too_few(*, limit):
    pass


@pytest.mark.parametrize("validate", [_validate_wrong_name, _validate_too_few])
def test_validate_must_accept_every_option(validate):
    with pytest.raises(TypeError, match="validate must take the options limit, name"):
        Registry().check(validate=validate)(good)


def test_validate_may_take_keyword_arguments_generically():
    def validate(**options):
        pass

    Registry().check(validate=validate)(good)


# Validating option values


def check_with_option(annotation: Any, validate=None) -> Check:
    """A check with one option `opt`, annotated with `annotation`."""
    param = inspect.Parameter("opt", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=annotation)
    return Check("demo", None, good, {"opt": param}, validate)


@pytest.mark.parametrize(
    ("annotation", "value", "expected"),
    [
        (int, 1, 1),
        (float, 1.5, 1.5),
        (float, 1, 1.0),
        (bool, True, True),
        (str, "text", "text"),
        (list, [1, "a"], [1, "a"]),
        (list[int], [1, 2], [1, 2]),
        (list[int], [], []),
        (list[float], [1, 2.5], [1.0, 2.5]),
        (list[list[int]], [[1], []], [[1], []]),
        (inspect.Parameter.empty, "anything", "anything"),
        (Any, "anything", "anything"),
        (int | str, 1.5, 1.5),  # unions can't be checked, so they're trusted
    ],
)
def test_option_values_matching_the_annotation_are_accepted(annotation, value, expected):
    resolved = check_with_option(annotation).resolve_options({"opt": value})["opt"]
    assert resolved == expected
    assert type(resolved) is type(expected)


@pytest.mark.parametrize(
    ("annotation", "value"),
    [
        (int, "1"),
        (int, 1.5),
        (int, True),
        (float, "1.5"),
        (float, True),
        (bool, 1),
        (str, 1),
        (list, "text"),
        (list[int], 1),
        (list[int], [1, "a"]),
        (list[int], [True]),
        (list[float], [True]),
    ],
)
def test_option_values_of_the_wrong_type_are_a_config_error(annotation, value):
    with pytest.raises(ConfigError, match=r"Option 'demo\.opt' must be .*, got "):
        check_with_option(annotation).resolve_options({"opt": value})


@pytest.mark.xfail(reason="with `from __future__ import annotations` the annotation is a string, so validation is silently skipped")
def test_string_annotations_are_validated_too(tmp_path):
    plugin = tmp_path / "stringly.py"
    plugin.write_text(
        "from __future__ import annotations\n"
        "from owlet.check import check\n"
        "@check\n"
        "async def stringly(ctx, *, limit: int = 1):\n"
        "    pass\n",
        encoding="utf-8",
    )

    stringly = discover_checks([plugin])["stringly"]

    with pytest.raises(ConfigError, match=r"Option 'stringly\.limit' must be int"):
        stringly.resolve_options({"limit": "nope"})


def test_unset_options_are_left_out_so_the_function_defaults_apply():
    assert check_with_option(int).resolve_options({}) == {}


def test_unknown_option_is_a_config_error_with_a_suggestion_and_the_available_ones():
    with pytest.raises(ConfigError) as error:
        check_with_option(int).resolve_options({"opts": 1})

    message = str(error.value)
    assert "Unknown option(s) for check 'demo': opts (did you mean opt?)" in message
    assert "Available: opt, timeout_seconds." in message


def test_validate_gets_set_values_merged_over_defaults():
    seen = {}

    def validate(**options):
        seen.update(options)

    checks = Registry()
    checks.check(validate=validate)(good)

    checks.checks["good"].resolve_options({"limit": 5})

    assert seen == {"limit": 5, "name": "x"}


def test_validate_runs_with_the_defaults_when_nothing_is_set():
    seen = {}

    def validate(**options):
        seen.update(options)

    checks = Registry()
    checks.check(validate=validate)(good)

    checks.checks["good"].resolve_options({})

    assert seen == {"limit": 1, "name": "x"}


def test_config_error_from_validate_names_the_check():
    def validate(**options):
        raise ConfigError("limit is too big.")

    with pytest.raises(ConfigError, match=r"^Check 'demo': limit is too big\.$"):
        check_with_option(int, validate).resolve_options({"opt": 1})


def test_crash_in_validate_is_not_a_config_error():
    def validate(**options):
        raise KeyError("oops")

    with pytest.raises(RuntimeError, match="validate crashed with KeyError") as error:
        check_with_option(int, validate).resolve_options({"opt": 1})

    assert not isinstance(error.value, ConfigError)
