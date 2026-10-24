import sys

import pytest

from owlet.check import registry
from owlet.discover import PLUGIN_PACKAGE


@pytest.fixture
def anyio_backend():
    """Run async tests on asyncio only: the harness uses asyncio.create_task and asyncio.timeout directly."""
    return "asyncio"


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
