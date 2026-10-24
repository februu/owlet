import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Hashable
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class Context:
    target: str
    http_client: httpx.AsyncClient
    timeout_seconds: float
    """Network timeout from [http].timeout_seconds, for checks that open their own connections instead of using http_client."""
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

    def get(self, url: str, *, follow_redirects: bool = True) -> Awaitable[httpx.Response]:
        """GET `url`, sent once per run and shared with every check that asks for the same URL."""
        return self._request("GET", url, follow_redirects)

    def head(self, url: str, *, follow_redirects: bool = True) -> Awaitable[httpx.Response]:
        """HEAD `url`, sent once per run and shared with every check that asks for the same URL."""
        return self._request("HEAD", url, follow_redirects)

    def _request(self, method: str, url: str, follow_redirects: bool) -> Awaitable[httpx.Response]:
        # Normalize so spellings of one URL share a request: `https://Example.com:443` and `https://example.com/#top` are the same.
        parsed = httpx.URL(url).copy_with(fragment=None)
        key = (method, parsed.scheme, parsed.host, parsed.port, parsed.raw_path, follow_redirects)
        return self._once(key, lambda: self.http_client.request(method, parsed, follow_redirects=follow_redirects))
