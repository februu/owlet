from urllib.parse import urlsplit, urlunsplit

from owlet.check import Result, Status, check
from owlet.context import Context

SLOW_RESPONSE_SECONDS = 1.5


@check
async def http_status(ctx: Context) -> Result:
    """Page responds with a 2xx status after following redirects."""
    response = await ctx.get(ctx.target)
    hops = len(response.history)
    redirects = f" after {hops} redirect(s) to {response.url}" if hops else ""
    return Result(Status.PASS if response.is_success else Status.FAIL, f"Got status code {response.status_code}{redirects}.")


@check
async def response_time(ctx: Context) -> Result:
    """Page responds within SLOW_RESPONSE_SECONDS, including redirects."""
    response = await ctx.get(ctx.target)
    # Use httpx's own per-request timing: the response may be shared, so timing our await would measure a cache hit.
    elapsed = sum(r.elapsed.total_seconds() for r in [*response.history, response])
    status = Status.PASS if elapsed < SLOW_RESPONSE_SECONDS else Status.FAIL
    return Result(status, f"Responded in {elapsed:.2f}s (limit {SLOW_RESPONSE_SECONDS}s).")


@check
async def https_redirect(ctx: Context) -> Result:
    """The http:// version of the site redirects to https://."""
    http_url = urlunsplit(urlsplit(ctx.target)._replace(scheme="http"))
    response = await ctx.get(http_url)
    if response.url.scheme == "https":
        return Result(Status.PASS, f"{http_url} redirects to {response.url}.")
    return Result(Status.FAIL, f"{http_url} is served without redirecting to HTTPS.")
