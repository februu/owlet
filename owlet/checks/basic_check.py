import asyncio

from owlet.check import Result


async def basic_check(url: str) -> list[Result]:
    # r = httpx.get(url, timeout=10, follow_redirects=True)
    await asyncio.sleep(2)  # Simulate a delay for the check
    return [
        Result(
            "basic_check - basic",
            True,
            "Got status code 200 with content length 100.",
        )
    ]


async def failing_check(url: str) -> list[Result]:
    await asyncio.sleep(2) 
    return [Result("failing_check", False, "")]
