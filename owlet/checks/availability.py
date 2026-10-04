import time
from urllib.parse import urlsplit, urlunsplit

from owlet.check import Result, check
from owlet.context import Context

SLOW_RESPONSE_SECONDS = 1.5


@check
async def http_status(ctx: Context) -> Result:
    """Page responds with a 2xx status after following redirects."""
    response = await ctx.http_client.get(ctx.target, follow_redirects=True)
    hops = len(response.history)
    redirects = f" after {hops} redirect(s) to {response.url}" if hops else ""
    return Result(response.is_success, f"Got status code {response.status_code}{redirects}.")


@check
async def response_time(ctx: Context) -> Result:
    """Page responds within SLOW_RESPONSE_SECONDS."""
    start = time.perf_counter()
    await ctx.http_client.get(ctx.target, follow_redirects=True)
    elapsed = time.perf_counter() - start
    return Result(elapsed < SLOW_RESPONSE_SECONDS, f"Responded in {elapsed:.2f}s (limit {SLOW_RESPONSE_SECONDS}s).")


@check
async def https_redirect(ctx: Context) -> Result:
    """The http:// version of the site redirects to https://."""
    http_url = urlunsplit(urlsplit(ctx.target)._replace(scheme="http"))
    response = await ctx.http_client.get(http_url, follow_redirects=True)
    if response.url.scheme == "https":
        return Result(True, f"{http_url} redirects to {response.url}.")
    return Result(False, f"{http_url} is served without redirecting to HTTPS.")
