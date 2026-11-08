"""resolve: validating a Config against the available checks and turning it into a Plan."""

import pytest

from owlet.check import Check, Registry
from owlet.config import Config, ConfigError, HttpConfig
from owlet.plan import resolve

TARGET = "https://site.test"


@pytest.fixture
def available() -> dict[str, Check]:
    checks = Registry()

    @checks.check
    async def alpha(ctx, *, limit: int = 1):
        pass

    @checks.check
    async def beta(ctx):
        pass

    @checks.check
    async def gamma(ctx):
        pass

    return checks.checks


def names(plan) -> list[str]:
    return [planned.check.name for planned in plan.checks]


def test_checks_run_in_active_checks_order_not_registration_order(available):
    assert names(resolve(Config(TARGET, ["gamma", "alpha"]), available)) == ["gamma", "alpha"]


def test_duplicate_active_checks_run_once(available):
    assert names(resolve(Config(TARGET, ["beta", "alpha", "beta"]), available)) == ["beta", "alpha"]


def test_only_replaces_active_checks_and_may_name_an_inactive_check(available):
    assert names(resolve(Config(TARGET, ["alpha"]), available, only=["gamma", "beta", "gamma"])) == ["gamma", "beta"]


def test_only_works_with_empty_active_checks(available):
    assert names(resolve(Config(TARGET, []), available, only=["alpha"])) == ["alpha"]


def test_nothing_to_run_is_a_config_error(available):
    with pytest.raises(ConfigError, match="No checks to run"):
        resolve(Config(TARGET, []), available)


@pytest.mark.parametrize(
    ("config_strict", "flag", "expected"),
    [(False, False, False), (True, False, True), (False, True, True), (True, True, True)],
)
def test_strict_is_on_if_either_the_config_or_the_flag_says_so(available, config_strict, flag, expected):
    assert resolve(Config(TARGET, ["alpha"], strict=config_strict), available, strict=flag).strict is expected


def test_target_and_http_settings_carry_over(available):
    http = HttpConfig(timeout_seconds=9.0)
    plan = resolve(Config(TARGET, ["alpha"], http=http), available)
    assert (plan.target, plan.http) == (TARGET, http)


def test_timeout_is_per_check_with_a_global_default(available):
    config = Config(TARGET, ["alpha", "beta"], check_timeout_seconds=30.0, check_timeouts={"beta": 2.0})
    assert [planned.timeout_seconds for planned in resolve(config, available).checks] == [30.0, 2.0]


def test_options_are_resolved_for_each_check(available):
    config = Config(TARGET, ["alpha", "beta"], check_options={"alpha": {"limit": 3}})
    assert [planned.options for planned in resolve(config, available).checks] == [{"limit": 3}, {}]


@pytest.mark.parametrize(
    "config",
    [
        Config(TARGET, ["alpah"]),
        Config(TARGET, ["beta"], check_options={"alpah": {}}),
        Config(TARGET, ["beta"], check_timeouts={"alpah": 1.0}),
    ],
    ids=["active_checks", "options-table", "timeout"],
)
def test_unknown_check_is_a_config_error_with_a_suggestion(available, config):
    with pytest.raises(ConfigError, match=r"Unknown checks: alpah \(did you mean alpha\?\)"):
        resolve(config, available)


def test_unknown_check_in_only_is_a_config_error(available):
    with pytest.raises(ConfigError, match="Unknown checks: nope"):
        resolve(Config(TARGET, ["alpha"]), available, only=["nope"])


def test_options_of_inactive_checks_are_validated_too(available):
    config = Config(TARGET, ["beta"], check_options={"alpha": {"limit": "lots"}})
    with pytest.raises(ConfigError, match=r"Option 'alpha\.limit' must be int"):
        resolve(config, available)


def test_validate_runs_for_inactive_checks_with_no_options_table():
    checks = Registry()

    def reject(**options):
        raise ConfigError("Bad default.")

    @checks.check(validate=reject)
    async def inactive(ctx):
        pass

    @checks.check
    async def active(ctx):
        pass

    with pytest.raises(ConfigError, match=r"Check 'inactive': Bad default\."):
        resolve(Config(TARGET, ["active"]), checks.checks)
