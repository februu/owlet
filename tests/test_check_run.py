"""Check.run: turning whatever a check function does into a list of Results."""

import asyncio
import socket
import ssl

import httpx
import pytest

from owlet.check import Registry, Result, Status

pytestmark = pytest.mark.anyio

PASS = Result(Status.PASS, "Fine.")


async def run(func, options=None, timeout=None) -> list[Result]:
    checks = Registry()
    checks.check(func)
    return await checks.checks[func.__name__].run(None, options or {}, timeout)


def statuses(results: list[Result]) -> list[Status]:
    return [result.status for result in results]


# What a check may produce


async def test_returning_one_result():
    async def check(ctx):
        return PASS

    assert statuses(await run(check)) == [Status.PASS]


@pytest.mark.parametrize("wrap", [list, tuple, iter], ids=["list", "tuple", "iterator"])
async def test_returning_an_iterable_of_results(wrap):
    async def check(ctx):
        return wrap([PASS, Result(Status.WARN, "Hm.")])

    assert statuses(await run(check)) == [Status.PASS, Status.WARN]


async def test_yielding_results():
    async def check(ctx):
        yield PASS
        yield Result(Status.WARN, "Hm.")

    assert statuses(await run(check)) == [Status.PASS, Status.WARN]


async def test_options_reach_the_check_as_keywords():
    async def check(ctx, *, limit=1):
        return Result(Status.PASS, f"Limit {limit}.")

    (result,) = await run(check, {"limit": 7})
    assert result.summary == "Limit 7."


async def test_every_result_gets_the_check_name_and_one_shared_duration():
    async def check(ctx):
        yield Result(Status.PASS, "One.", check_name="spoofed", duration_seconds=99.0)
        yield Result(Status.PASS, "Two.")

    first, second = await run(check)

    assert first.check_name == second.check_name == "check"
    assert first.duration_seconds == second.duration_seconds != 99.0


# A check that misbehaves is an ERROR


@pytest.mark.parametrize("output", [[], ()], ids=["list", "tuple"])
async def test_returning_no_results_is_an_error(output):
    async def check(ctx):
        return output

    (result,) = await run(check)
    assert (result.status, result.summary) == (Status.ERROR, "Check produced no results.")


async def test_yielding_no_results_is_an_error():
    async def check(ctx):
        return
        yield

    (result,) = await run(check)
    assert (result.status, result.summary) == (Status.ERROR, "Check produced no results.")


@pytest.mark.parametrize(
    ("output", "named"),
    [(None, "NoneType"), ("text", "str"), (5, "int"), ([PASS, "text"], "str")],
    ids=["none", "string", "number", "list-with-a-string"],
)
async def test_returning_something_else_is_an_error_naming_the_type(output, named):
    async def check(ctx):
        return output

    (result,) = await run(check)
    assert result.status is Status.ERROR
    assert named in result.summary


async def test_yielding_something_else_is_an_error_and_keeps_earlier_results():
    async def check(ctx):
        yield PASS
        yield "text"

    results = await run(check)
    assert statuses(results) == [Status.PASS, Status.ERROR]
    assert "str" in results[1].summary


async def test_building_an_invalid_result_is_an_error():
    async def check(ctx):
        return Result(Status.PASS, "two\nlines")

    (result,) = await run(check)
    assert result.status is Status.ERROR
    assert "one line" in result.summary


# Exceptions: trouble reaching the site is a FAIL, a bug in the check is an ERROR


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
        httpx.TooManyRedirects("loop"),
        httpx.InvalidURL("bad"),
        OSError("unreachable"),
        ConnectionRefusedError("refused"),
        ConnectionResetError("reset"),
        TimeoutError("slow"),
        socket.gaierror("no such host"),
        ssl.SSLError("bad certificate"),
    ],
    ids=lambda e: type(e).__name__,
)
async def test_network_errors_are_a_fail_without_a_traceback(error):
    async def check(ctx):
        raise error

    (result,) = await run(check)
    assert result.status is Status.FAIL
    assert result.summary.startswith(type(error).__name__)
    assert result.traceback is None


async def test_raise_for_status_is_a_fail():
    async def check(ctx):
        httpx.Response(500, request=httpx.Request("GET", "https://site.test")).raise_for_status()

    (result,) = await run(check)
    assert result.status is Status.FAIL


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("missing"),
        FileExistsError("exists"),
        IsADirectoryError("directory"),
        NotADirectoryError("not directory"),
        PermissionError("denied"),
        ValueError("bad"),
        KeyError("key"),
        RuntimeError("bug"),
    ],
    ids=lambda e: type(e).__name__,
)
async def test_other_exceptions_are_an_error_with_a_traceback(error):
    async def check(ctx):
        raise error

    (result,) = await run(check)
    assert result.status is Status.ERROR
    assert result.summary.startswith(type(error).__name__)
    assert type(error).__name__ in result.traceback


async def test_traceback_shows_the_check_but_not_the_runner():
    async def crashing_check(ctx):
        raise ValueError("boom")

    (result,) = await run(crashing_check)

    assert "crashing_check" in result.traceback
    assert "ValueError: boom" in result.traceback
    assert "_collect" not in result.traceback


@pytest.mark.parametrize(
    ("error", "status"),
    [(ValueError("first\n\n  \nsecond\nthird"), Status.ERROR), (OSError("first\n\n  \nsecond\nthird"), Status.FAIL)],
    ids=["error", "fail"],
)
async def test_multi_line_exception_message_splits_into_summary_and_details(error, status):
    async def check(ctx):
        raise error

    (result,) = await run(check)
    assert result.status is status
    assert result.summary == f"{type(error).__name__}: first"
    assert result.details == ("second", "third")


@pytest.mark.parametrize(("error", "status"), [(ValueError(), Status.ERROR), (httpx.ConnectError(""), Status.FAIL)], ids=["error", "fail"])
async def test_exception_without_a_message_is_described_by_its_type(error, status):
    async def check(ctx):
        raise error

    (result,) = await run(check)
    assert (result.status, result.summary) == (status, type(error).__name__)


@pytest.mark.parametrize(
    ("error", "status"), [(ValueError("boom"), Status.ERROR), (httpx.ConnectError("refused"), Status.FAIL)], ids=["error", "fail"]
)
async def test_results_yielded_before_a_crash_are_kept(error, status):
    async def check(ctx):
        yield PASS
        raise error

    assert statuses(await run(check)) == [Status.PASS, status]


# Timeouts


async def test_timeout_is_a_fail_without_a_traceback():
    async def check(ctx):
        await asyncio.sleep(60)

    (result,) = await run(check, timeout=0.01)

    assert (result.status, result.summary) == (Status.FAIL, "Timed out after 0.01s.")
    assert result.traceback is None


async def test_results_yielded_before_a_timeout_are_kept():
    async def check(ctx):
        yield PASS
        await asyncio.sleep(60)

    assert statuses(await run(check, timeout=0.01)) == [Status.PASS, Status.FAIL]


async def test_timeout_is_reported_even_if_the_check_raises_while_being_stopped():
    async def check(ctx):
        try:
            await asyncio.sleep(60)
        finally:
            raise ValueError("cleanup failed")  # raising during cancellation is the point

    (result,) = await run(check, timeout=0.01)
    assert result.summary == "Timed out after 0.01s."


async def test_timeout_error_raised_by_the_check_itself_is_not_reported_as_the_deadline():
    async def check(ctx):
        raise TimeoutError("socket timed out")

    (result,) = await run(check, timeout=60)
    assert (result.status, result.summary) == (Status.FAIL, "TimeoutError: socket timed out")


async def test_check_finishing_in_time_is_unaffected_by_the_timeout():
    async def check(ctx):
        return PASS

    assert statuses(await run(check, timeout=60)) == [Status.PASS]


# Async generators get closed however they stop


@pytest.mark.parametrize("timeout", [None, 0.01], ids=["invalid-output", "timeout"])
async def test_generator_cleanup_runs_when_it_is_stopped_early(timeout):
    cleaned_up = []

    async def check(ctx):
        try:
            if timeout:
                await asyncio.sleep(60)
            yield "not a result"
            yield PASS
        finally:
            cleaned_up.append(True)

    await run(check, timeout=timeout)

    assert cleaned_up == [True]
