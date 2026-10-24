import pytest

from owlet.check import Registry, Result, Status, check, registry

pytestmark = pytest.mark.anyio


async def test_check_runs_and_is_labelled():
    checks = Registry()

    @checks.check
    async def always_passes(ctx):
        return Result(Status.PASS, "Fine.")

    (result,) = await checks.checks["always_passes"].run(ctx=None, options={})

    assert (result.status, result.summary, result.check_name) == (Status.PASS, "Fine.", "always_passes")
    assert result.duration_seconds is not None


async def test_global_registry_is_restored_between_tests_part_1():
    @check
    async def leaked(ctx):
        return Result(Status.PASS, "Fine.")

    assert "leaked" in registry.checks


async def test_global_registry_is_restored_between_tests_part_2():
    assert "leaked" not in registry.checks
