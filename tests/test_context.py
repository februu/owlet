"""Context: requests shared between checks."""

import asyncio

import httpx
import pytest

from owlet.context import Context

pytestmark = pytest.mark.anyio

URL = "https://site.test/"


def context(client: httpx.AsyncClient) -> Context:
    return Context(target=URL, http_client=client, timeout_seconds=5.0)


async def request_count(site, *urls: str) -> int:
    async with httpx.AsyncClient() as client:
        ctx = context(client)
        await asyncio.gather(*(ctx.get(url) for url in urls))
    return len(site.requests)


async def test_concurrent_callers_share_one_request_and_response(site):
    async with httpx.AsyncClient() as client:
        ctx = context(client)
        first, second = await asyncio.gather(ctx.get(URL), ctx.get(URL))

    assert first is second
    assert len(site.requests) == 1


async def test_later_callers_reuse_the_finished_request(site):
    async with httpx.AsyncClient() as client:
        ctx = context(client)
        first = await ctx.get(URL)
        second = await ctx.get(URL)

    assert first is second
    assert len(site.requests) == 1


async def test_contexts_do_not_share_requests(site):
    async with httpx.AsyncClient() as client:
        await context(client).get(URL)
        await context(client).get(URL)

    assert len(site.requests) == 2


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("https://site.test", "https://site.test/"),
        ("https://site.test/", "https://SITE.test/"),
        ("https://site.test/", "HTTPS://site.test/"),
        ("https://site.test/", "https://site.test:443/"),
        ("http://site.test/", "http://site.test:80/"),
        ("https://site.test/", "https://site.test/#top"),
        ("https://site.test/a?x=1", "https://site.test/a?x=1#top"),
    ],
)
async def test_spellings_of_one_url_share_a_request(site, first, second):
    assert await request_count(site, first, second) == 1


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("https://site.test/", "http://site.test/"),
        ("https://site.test/", "https://other.test/"),
        ("https://site.test/", "https://site.test:8443/"),
        ("https://site.test/a", "https://site.test/b"),
        ("https://site.test/a", "https://site.test/a/"),
        ("https://site.test/a", "https://site.test/A"),
        ("https://site.test/?x=1", "https://site.test/?x=2"),
        ("https://site.test/", "https://site.test/?x=1"),
        pytest.param(
            "https://one:secret@site.test/",
            "https://two:secret@site.test/",
            marks=pytest.mark.xfail(reason="the cache key leaves out the userinfo, so the second caller gets the first user's response"),
        ),
    ],
)
async def test_different_urls_get_their_own_request(site, first, second):
    assert await request_count(site, first, second) == 2


async def test_get_and_head_do_not_share(site):
    async with httpx.AsyncClient() as client:
        ctx = context(client)
        await asyncio.gather(ctx.get(URL), ctx.head(URL))

    assert sorted(request.method for request in site.requests) == ["GET", "HEAD"]


@pytest.mark.parametrize("method", ["get", "head"])
async def test_redirect_following_is_shared_separately(site, method):
    site.redirect({URL: "https://site.test/next"})

    async with httpx.AsyncClient() as client:
        ctx = context(client)
        followed = await getattr(ctx, method)(URL)
        unfollowed = await getattr(ctx, method)(URL, follow_redirects=False)

    assert followed.status_code == 200
    assert unfollowed.status_code == 302


async def test_redirects_are_followed_by_default(site):
    site.redirect({URL: "https://site.test/next"})

    async with httpx.AsyncClient() as client:
        response = await context(client).get(URL)

    assert str(response.url) == "https://site.test/next"


async def test_failed_request_is_shared_and_not_retried(site):
    def refuse(request):
        raise httpx.ConnectError("refused")

    site.respond = refuse

    async with httpx.AsyncClient() as client:
        ctx = context(client)
        results = await asyncio.gather(ctx.get(URL), ctx.get(URL), return_exceptions=True)
        with pytest.raises(httpx.ConnectError):
            await ctx.get(URL)

    assert [type(result) for result in results] == [httpx.ConnectError, httpx.ConnectError]
    assert len(site.requests) == 1


async def test_invalid_url_raises_invalid_url(site):
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.InvalidURL):
            context(client).get("https://site.test:abc/")


async def test_a_caller_giving_up_does_not_cancel_the_request_for_others(site):
    release = asyncio.Event()

    async def respond_when_released(request):
        await release.wait()
        return httpx.Response(200)

    site.respond = respond_when_released

    async with httpx.AsyncClient() as client:
        ctx = context(client)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await ctx.get(URL)
        waiting = ctx.get(URL)
        release.set()
        response = await waiting

    assert response.status_code == 200
    assert len(site.requests) == 1


async def test_close_cancels_requests_still_running(site):
    started = asyncio.Event()
    cancelled = []

    async def hang(request):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(str(request.url))
            raise

    site.respond = hang

    async with httpx.AsyncClient() as client:
        ctx = context(client)
        ctx.get(URL)
        await started.wait()
        await ctx.close()

    assert cancelled == [URL]


async def test_close_is_fine_with_finished_and_failed_requests(site):
    def respond(request):
        if request.url.path == "/fails":
            raise httpx.ConnectError("refused")
        return httpx.Response(200)

    site.respond = respond

    async with httpx.AsyncClient() as client:
        ctx = context(client)
        await ctx.get(URL)
        with pytest.raises(httpx.ConnectError):
            await ctx.get("https://site.test/fails")
        await ctx.close()


async def test_close_without_any_requests_is_fine(site):
    async with httpx.AsyncClient() as client:
        await context(client).close()
