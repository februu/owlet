import httpx

from owlet.check import Result


def basic_check(url: str) -> list[Result]:
    r = httpx.get(url, timeout=10, follow_redirects=True)
    return [
        Result(
            "basic_check - basic",
            True,
            f"Got status code {r.status_code} with content length {len(r.text)}.",
        )
    ]



def failing_check(url: str) -> list[Result]:
    return [Result("failing_check", False, "")]
