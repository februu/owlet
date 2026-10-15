import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Hashable
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class Context:

    target: str
    http_client: httpx.AsyncClient
    _cache: dict[Hashable, asyncio.Task] = field(default_factory=dict, init=False, repr=False)

    def once[T](self, key: Hashable, factory: Callable[[], Coroutine[Any, Any, T]]) -> Awaitable[T]:
        """Run `factory` at most once per key; every caller awaits the same task, even while it's still running."""
        if key not in self._cache:
            self._cache[key] = asyncio.create_task(factory())
        return self._cache[key]

    def get(self, url: str) -> Awaitable[httpx.Response]:
        """GET `url` following redirects, shared across all checks in this run."""
        return self.once(("GET", url), lambda: self.http_client.get(url, follow_redirects=True))
