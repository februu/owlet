import time
from urllib.parse import urlsplit, urlunsplit

from owlet.check import Result
from owlet.context import Context

SLOW_RESPONSE_SECONDS = 1.5


async def http_status(ctx: Context) -> list[Result]:
    response = await ctx.http_client.get(ctx.target, follow_redirects=True)
    hops = len(response.history)
    redirects = f" after {hops} redirect(s) to {response.url}" if hops else ""
    return [
        Result(
            "http_status",
            response.is_success,
            f"Got status code {response.status_code}{redirects}.",
        )
    ]


async def response_time(ctx: Context) -> list[Result]:
    start = time.perf_counter()
    await ctx.http_client.get(ctx.target, follow_redirects=True)
    elapsed = time.perf_counter() - start
    return [
        Result(
            "response_time",
            elapsed < SLOW_RESPONSE_SECONDS,
            f"Responded in {elapsed:.2f}s (limit {SLOW_RESPONSE_SECONDS}s).",
        )
    ]


async def https_redirect(ctx: Context) -> list[Result]:
    http_url = urlunsplit(urlsplit(ctx.target)._replace(scheme="http"))
    response = await ctx.http_client.get(http_url, follow_redirects=True)
    if response.url.scheme == "https":
        return [Result("https_redirect", True, f"{http_url} redirects to {response.url}.")]
    return [Result("https_redirect", False, f"{http_url} is served without redirecting to HTTPS.")]
