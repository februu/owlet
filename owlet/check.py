from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from owlet.context import Context


@dataclass(frozen=True)
class Result:
    """Represents the result of a check."""

    check_name : str
    success : bool
    content : str | None = None



type Check = Callable[[Context], Awaitable[list[Result]]]
