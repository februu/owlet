from owlet.check import Result
from owlet.context import Context


async def basic_check(ctx: Context, url: str) -> list[Result]:
    return [
        Result(
            "basic_check - basic",
            True,
            "Got status code 200 with content length 100.",
        )
    ]



async def failing_check(ctx: Context, url: str) -> list[Result]:
    return [Result("failing_check", False, "")]
