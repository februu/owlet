from itertools import pairwise

import httpx

from owlet.check import Result, Status, check
from owlet.config import ConfigError
from owlet.context import Context


def _validate_http_status(*, max_redirects: int) -> None:
    if max_redirects < 0:
        raise ConfigError(f"max_redirects must be at least 0, got {max_redirects}.")


@check(validate=_validate_http_status)
async def http_status(ctx: Context, *, max_redirects: int = 3) -> Result:
    """Target responds with a 2xx status after following redirects. Warns after more than `max_redirects` redirects."""
    response = await ctx.get(ctx.target)
    redirects = len(response.history)
    data = {"status_code": response.status_code, "final_url": str(response.url), "redirects": redirects}
    details = _hops(response)
    ending = f" after {redirects} redirect(s), ending at {response.url}" if redirects else ""

    if not response.is_success:
        # httpx follows every redirect it can, so a 3xx at the end of the chain usually means the Location is missing.
        no_location = 300 <= response.status_code < 400 and "Location" not in response.headers
        note = " with no Location header" if no_location else ""
        return Result(Status.FAIL, f"Got {response.status_code}{note}{ending}.", details=details, data=data)
    if redirects > max_redirects:
        summary = f"Got {response.status_code} after {redirects} redirect(s) (more than {max_redirects}), ending at {response.url}."
        return Result(Status.WARN, summary, details=details, data=data)
    return Result(Status.PASS, f"Got {response.status_code}{ending}.", details=details, data=data)


def _hops(response: httpx.Response) -> list[str]:
    """Each redirect in the chain that led to `response`, as `302 <from> -> <to>`."""
    chain = [*response.history, response]
    return [f"{hop.status_code} {hop.url} -> {following.url}" for hop, following in pairwise(chain)]
