import inspect
import sys
from collections.abc import Callable

import httpx
import pytest

from owlet.check import Registry, registry
from owlet.config import HttpConfig
from owlet.discover import PLUGIN_PACKAGE, discover_checks
from owlet.plan import Plan, PlannedCheck

TARGET = "https://site.test"


@pytest.fixture
def anyio_backend():
    """Run async tests on asyncio only: the harness uses asyncio.create_task and asyncio.timeout directly."""
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
def builtin_checks():
    """Import the built-in checks once, up front, so isolated_registry's snapshot includes them.

    Their modules stay cached in sys.modules, so importing them again wouldn't re-register them after a restore.
    """
    discover_checks()


@pytest.fixture(autouse=True)
def isolated_registry():
    """Undo checks registered and plugin modules imported by a test, so names don't collide in later tests."""
    checks = registry.checks
    modules = set(sys.modules)
    yield
    registry._checks.clear()
    registry._checks.update(checks)
    for name in set(sys.modules) - modules:
        if name == PLUGIN_PACKAGE or name.startswith(f"{PLUGIN_PACKAGE}."):
            del sys.modules[name]


class FakeSite:
    """Answers HTTP requests in memory. Everything above the transport is real httpx, including redirects and event hooks."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.client_kwargs: dict = {}
        self.respond: Callable = lambda request: httpx.Response(200)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.respond(request)
        return await response if inspect.isawaitable(response) else response

    def redirect(self, routes: dict[str, str]) -> None:
        """Answer each URL in `routes` with a redirect to its value, and any other URL with 200."""

        def respond(request: httpx.Request) -> httpx.Response:
            location = routes.get(str(request.url))
            return httpx.Response(302, headers={"Location": location}) if location else httpx.Response(200)

        self.respond = respond


@pytest.fixture
def site(monkeypatch) -> FakeSite:
    """Route every httpx.AsyncClient created during the test to a FakeSite, and record the settings it was created with."""
    fake = FakeSite()
    real_client = httpx.AsyncClient

    def client(**kwargs) -> httpx.AsyncClient:
        fake.client_kwargs = kwargs
        return real_client(transport=httpx.MockTransport(fake), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return fake


@pytest.fixture
def plan_for():
    """A factory for Plans running the given check functions, in order, without going through a config."""

    def make(
        *funcs: Callable,
        target: str = TARGET,
        strict: bool = False,
        http: HttpConfig | None = None,
        timeout: float = 5.0,
        timeouts: dict[str, float] | None = None,
    ) -> Plan:
        checks = Registry()
        for func in funcs:
            checks.check(func)
        planned = [PlannedCheck(check, {}, (timeouts or {}).get(name, timeout)) for name, check in checks.checks.items()]
        return Plan(target, strict, planned, http or HttpConfig())

    return make
