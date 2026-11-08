"""Owlet: running a whole Plan concurrently, judging its results, and the HTTP client the checks share."""

import asyncio

import httpx
import pytest

from owlet.check import Result, Status
from owlet.config import HttpConfig
from owlet.owlet import ExitCode, Owlet

pytestmark = pytest.mark.anyio

PASS = Result(Status.PASS, "Fine.")
HEADERS = HttpConfig(headers={"X-Token": "secret"})


def summary_by_check(results: list[Result]) -> dict[str, Status]:
    return {result.check_name: result.status for result in results}


# Running


async def test_results_follow_plan_order_not_finishing_order(site, plan_for):
    second_finished = asyncio.Event()

    async def first(ctx):
        await second_finished.wait()
        return Result(Status.PASS, "First.")

    async def second(ctx):
        second_finished.set()
        return Result(Status.PASS, "Second.")

    results = await Owlet(plan_for(first, second)).run()

    assert [result.check_name for result in results] == ["first", "second"]


async def test_results_of_one_check_stay_together_and_in_order(site, plan_for):
    async def first(ctx):
        yield Result(Status.PASS, "1a.")
        await asyncio.sleep(0)
        yield Result(Status.PASS, "1b.")

    async def second(ctx):
        return Result(Status.PASS, "2.")

    results = await Owlet(plan_for(first, second)).run()

    assert [result.summary for result in results] == ["1a.", "1b.", "2."]


async def test_checks_run_concurrently(site, plan_for):
    both_running = asyncio.Barrier(2)

    async def first(ctx):
        await both_running.wait()
        return PASS

    async def second(ctx):
        await both_running.wait()
        return PASS

    results = await Owlet(plan_for(first, second, timeout=2.0)).run()

    assert summary_by_check(results) == {"first": Status.PASS, "second": Status.PASS}


async def test_a_crashing_check_does_not_stop_the_others(site, plan_for):
    crashed = asyncio.Event()

    async def crashes(ctx):
        crashed.set()
        raise ValueError("boom")

    async def carries_on(ctx):
        await crashed.wait()
        await asyncio.sleep(0)
        return PASS

    results = await Owlet(plan_for(crashes, carries_on)).run()

    assert summary_by_check(results) == {"crashes": Status.ERROR, "carries_on": Status.PASS}


async def test_a_timed_out_check_does_not_stop_the_others_and_timeouts_are_per_check(site, plan_for):
    timed_out = asyncio.Event()

    async def slow(ctx):
        try:
            await asyncio.sleep(60)
        finally:
            timed_out.set()

    async def carries_on(ctx):
        await timed_out.wait()
        return PASS

    results = await Owlet(plan_for(slow, carries_on, timeouts={"slow": 0.01})).run()

    assert summary_by_check(results) == {"slow": Status.FAIL, "carries_on": Status.PASS}


@pytest.mark.xfail(raises=asyncio.CancelledError, reason="escapes Check.run, then task.result() loses every result")
def test_stray_cancelled_error_in_a_check_is_an_error_and_the_others_finish(site, plan_for):
    """Uses asyncio.run so the CancelledError can't reach the event loop running the test. For sys.exit, see test_cli."""

    async def misbehaves(ctx):
        raise asyncio.CancelledError

    async def carries_on(ctx):
        return PASS

    results = asyncio.run(Owlet(plan_for(misbehaves, carries_on)).run())

    assert summary_by_check(results) == {"misbehaves": Status.ERROR, "carries_on": Status.PASS}


async def test_cancelling_the_run_itself_still_stops_it(site, plan_for):
    """Real cancellation, as with Ctrl+C, has to keep working however stray CancelledErrors from checks are handled."""
    running = asyncio.Event()
    stopped = asyncio.Event()

    async def waits(ctx):
        running.set()
        try:
            await asyncio.sleep(60)
        finally:
            stopped.set()

    run = asyncio.create_task(Owlet(plan_for(waits)).run())
    await running.wait()
    run.cancel()

    with pytest.raises(asyncio.CancelledError):
        await run
    assert stopped.is_set()


# What checks get to work with


async def test_checks_get_the_target_and_network_timeout(site, plan_for):
    seen = {}

    async def inspects(ctx):
        seen.update(target=ctx.target, timeout=ctx.timeout_seconds)
        return PASS

    await Owlet(plan_for(inspects, target="https://other.test", http=HttpConfig(timeout_seconds=9.0))).run()

    assert seen == {"target": "https://other.test", "timeout": 9.0}


async def test_checks_share_requests_within_a_run_but_not_between_runs(site, plan_for):
    async def first(ctx):
        await ctx.get(ctx.target)
        return PASS

    async def second(ctx):
        await ctx.get(ctx.target)
        return PASS

    owlet = Owlet(plan_for(first, second))

    await owlet.run()
    assert len(site.requests) == 1
    await owlet.run()
    assert len(site.requests) == 2


async def test_shared_request_failure_fails_every_check_that_waits_on_it(site, plan_for):
    def refuse(request):
        raise httpx.ConnectError("refused")

    site.respond = refuse

    async def first(ctx):
        await ctx.get(ctx.target)
        return PASS

    async def second(ctx):
        await ctx.get(ctx.target)
        return PASS

    results = await Owlet(plan_for(first, second)).run()

    assert summary_by_check(results) == {"first": Status.FAIL, "second": Status.FAIL}
    assert len(site.requests) == 1


async def test_a_timed_out_check_does_not_cancel_a_request_another_check_waits_on(site, plan_for):
    impatient_gave_up = asyncio.Event()

    async def respond_late(request):
        await impatient_gave_up.wait()
        return httpx.Response(200)

    site.respond = respond_late

    async def impatient(ctx):
        try:
            await ctx.get(ctx.target)
        finally:
            impatient_gave_up.set()

    async def patient(ctx):
        response = await ctx.get(ctx.target)
        return Result(Status.PASS, f"Got {response.status_code}.")

    results = await Owlet(plan_for(impatient, patient, timeouts={"impatient": 0.01})).run()

    assert summary_by_check(results) == {"impatient": Status.FAIL, "patient": Status.PASS}
    assert len(site.requests) == 1


async def test_request_only_a_timed_out_check_waited_on_is_cancelled_when_the_run_ends(site, plan_for):
    cancelled = []

    async def hang(request):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    site.respond = hang

    async def impatient(ctx):
        await ctx.get(ctx.target)

    async with asyncio.timeout(5):
        results = await Owlet(plan_for(impatient, timeout=0.01)).run()

    assert summary_by_check(results) == {"impatient": Status.FAIL}
    assert cancelled == [True]


async def test_http_client_is_closed_after_the_run(site, plan_for):
    clients = []

    async def keeps_client(ctx):
        clients.append(ctx.http_client)
        return PASS

    await Owlet(plan_for(keeps_client)).run()

    assert clients[0].is_closed


# Client settings


async def test_http_settings_reach_the_client(site, plan_for):
    settings = HttpConfig(timeout_seconds=9.0, verify=False, max_connections=7)

    async def noop(ctx):
        return PASS

    await Owlet(plan_for(noop, http=settings)).run()

    assert site.client_kwargs["timeout"] == 9.0
    assert site.client_kwargs["verify"] is False
    assert site.client_kwargs["limits"].max_connections == 7


async def test_user_agent_is_sent_to_every_host(site, plan_for):
    async def visits_two_hosts(ctx):
        await ctx.get("https://site.test")
        await ctx.get("https://other.test")
        return PASS

    await Owlet(plan_for(visits_two_hosts, http=HttpConfig(user_agent="custom/1.0"))).run()

    assert [request.headers["User-Agent"] for request in site.requests] == ["custom/1.0", "custom/1.0"]


# Configured headers stay on the target


async def _get_target(ctx):
    await ctx.get(ctx.target)
    return PASS


def tokens_sent(site) -> list[tuple[str, str | None]]:
    return [(str(request.url), request.headers.get("X-Token")) for request in site.requests]


@pytest.mark.parametrize(
    ("target", "next_hop", "token_on_next_hop"),
    [
        ("https://site.test/", "https://site.test/next", "secret"),
        ("https://site.test/", "https://site.test:8443/next", "secret"),
        ("https://site.test/", "https://other.test/", None),
        ("https://site.test/", "https://sub.site.test/", None),
        ("https://site.test/", "https://site.test.evil.test/", None),
        ("https://site.test/", "http://site.test/next", None),
        ("http://site.test/", "http://site.test/next", "secret"),
        ("http://site.test/", "https://site.test/next", "secret"),
        ("http://site.test/", "http://other.test/", None),
    ],
)
async def test_headers_on_a_redirect_only_go_to_the_target_host_and_never_downgrade(site, plan_for, target, next_hop, token_on_next_hop):
    site.redirect({target: next_hop})

    await Owlet(plan_for(_get_target, target=target, http=HEADERS)).run()

    assert tokens_sent(site) == [(target, "secret"), (next_hop, token_on_next_hop)]


async def test_headers_return_when_a_redirect_comes_back_to_the_target(site, plan_for):
    site.redirect({"https://site.test/": "https://other.test/", "https://other.test/": "https://site.test/back"})

    await Owlet(plan_for(_get_target, target="https://site.test/", http=HEADERS)).run()

    assert tokens_sent(site) == [
        ("https://site.test/", "secret"),
        ("https://other.test/", None),
        ("https://site.test/back", "secret"),
    ]


async def test_headers_are_not_sent_to_other_hosts_a_check_requests_directly(site, plan_for):
    async def visits_two_hosts(ctx):
        await ctx.http_client.get("https://other.test/")
        await ctx.http_client.get("https://site.test/")
        return PASS

    await Owlet(plan_for(visits_two_hosts, http=HEADERS)).run()

    assert tokens_sent(site) == [("https://other.test/", None), ("https://site.test/", "secret")]


@pytest.mark.parametrize(
    ("target", "request_url"),
    [("https://SITE.test/", "https://site.test/"), ("https://bücher.test/", "https://xn--bcher-kva.test/")],
    ids=["case", "international"],
)
async def test_target_host_compares_the_way_httpx_normalizes_it(site, plan_for, target, request_url):
    async def get_normalized(ctx):
        await ctx.get(request_url)
        return PASS

    await Owlet(plan_for(get_normalized, target=target, http=HEADERS)).run()

    assert tokens_sent(site) == [(request_url, "secret")]


# Judging results


@pytest.mark.parametrize(
    ("status", "strict", "fails"),
    [
        (Status.PASS, False, False),
        (Status.PASS, True, False),
        (Status.SKIP, False, False),
        (Status.SKIP, True, False),
        (Status.WARN, False, False),
        (Status.WARN, True, True),
        (Status.FAIL, False, True),
        (Status.FAIL, True, True),
        (Status.ERROR, False, True),
        (Status.ERROR, True, True),
    ],
)
def test_which_results_fail_the_run(plan_for, status, strict, fails):
    owlet = Owlet(plan_for(strict=strict))
    result = Result(status, "Summary.")

    assert owlet.is_failure(result) is fails
    assert owlet.exit_code([PASS, result]) is (ExitCode.CHECKS_FAILED if fails else ExitCode.OK)


def test_no_results_is_ok(plan_for):
    assert Owlet(plan_for()).exit_code([]) is ExitCode.OK
