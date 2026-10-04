from collections.abc import AsyncIterator

from owlet.check import Result, check
from owlet.context import Context

MAX_VALUE_LENGTH = 80


def _shorten(value: str) -> str:
    return value if len(value) <= MAX_VALUE_LENGTH else value[: MAX_VALUE_LENGTH - 3] + "..."


@check
async def security_headers(ctx: Context) -> AsyncIterator[Result]:
    """Common security headers are set, one result per header."""
    response = await ctx.http_client.get(ctx.target, follow_redirects=True)
    headers = response.headers
    csp = headers.get("Content-Security-Policy", "")

    def header_result(name: str, passed: bool, missing_message: str) -> Result:
        return Result(passed, _shorten(headers[name]) if passed else missing_message, name=name)

    if response.url.scheme == "https":
        yield header_result("Strict-Transport-Security", "Strict-Transport-Security" in headers, "Header missing.")
    yield header_result("Content-Security-Policy", bool(csp), "Header missing.")
    yield header_result(
        "X-Content-Type-Options",
        headers.get("X-Content-Type-Options", "").lower() == "nosniff",
        "Expected 'nosniff'.",
    )
    yield header_result("Referrer-Policy", "Referrer-Policy" in headers, "Header missing.")

    if "frame-ancestors" in csp:
        yield Result(True, "Protected by CSP frame-ancestors.", name="clickjacking")
    elif "X-Frame-Options" in headers:
        yield Result(True, f"X-Frame-Options: {headers['X-Frame-Options']}", name="clickjacking")
    else:
        yield Result(False, "Neither X-Frame-Options nor CSP frame-ancestors set.", name="clickjacking")
