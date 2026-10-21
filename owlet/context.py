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

    def _once[T](self, key: Hashable, factory: Callable[[], Coroutine[Any, Any, T]]) -> Awaitable[T]:
        """Run `factory` at most once per key; every caller awaits the same task, even while it's still running."""
        if key not in self._cache:
            self._cache[key] = asyncio.create_task(factory())
        return asyncio.shield(self._cache[key])

    async def close(self) -> None:
        """Cancel shared tasks still running, e.g. ones only a timed-out check was waiting on."""
        pending = [task for task in self._cache.values() if not task.done()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def get(self, url: str) -> Awaitable[httpx.Response]:
        """GET `url` following redirects, shared across all checks in this run."""
        return self._once(("GET", url), lambda: self.http_client.get(url, follow_redirects=True))
