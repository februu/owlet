from owlet.check import Result
from owlet.context import Context

MAX_VALUE_LENGTH = 80


def _shorten(value: str) -> str:
    return value if len(value) <= MAX_VALUE_LENGTH else value[: MAX_VALUE_LENGTH - 3] + "..."


async def security_headers(ctx: Context) -> list[Result]:
    response = await ctx.http_client.get(ctx.target, follow_redirects=True)
    headers = response.headers
    csp = headers.get("Content-Security-Policy", "")

    def header_result(name: str, passed: bool, missing_message: str) -> Result:
        return Result(
            f"security_headers - {name}",
            passed,
            _shorten(headers[name]) if passed else missing_message,
        )

    results = []
    if response.url.scheme == "https":
        results.append(header_result("Strict-Transport-Security", "Strict-Transport-Security" in headers, "Header missing."))
    results.append(header_result("Content-Security-Policy", bool(csp), "Header missing."))
    results.append(
        header_result(
            "X-Content-Type-Options",
            headers.get("X-Content-Type-Options", "").lower() == "nosniff",
            "Expected 'nosniff'.",
        )
    )
    results.append(header_result("Referrer-Policy", "Referrer-Policy" in headers, "Header missing."))

    if "frame-ancestors" in csp:
        results.append(Result("security_headers - clickjacking", True, "Protected by CSP frame-ancestors."))
    elif "X-Frame-Options" in headers:
        results.append(Result("security_headers - clickjacking", True, f"X-Frame-Options: {headers['X-Frame-Options']}"))
    else:
        results.append(Result("security_headers - clickjacking", False, "Neither X-Frame-Options nor CSP frame-ancestors set."))
    return results
