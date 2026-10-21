from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from owlet.check import Check
from owlet.config import Config, ConfigError
from owlet.suggest import with_suggestion


@dataclass(frozen=True)
class PlannedCheck:
    """One check to run, with its options already validated."""

    check: Check
    options: Mapping[str, Any]
    timeout_seconds: float


@dataclass(frozen=True)
class Plan:
    """Everything a run needs, fully validated: the target, strict mode, and the checks to run in output order."""

    target: str
    strict: bool
    checks: Sequence[PlannedCheck]


def resolve(config: Config, available: Mapping[str, Check], *, only: Sequence[str] | None = None, strict: bool = False) -> Plan:
    """Validate `config` against the `available` checks and turn it into a Plan. Raises ConfigError for anything unusable.

    `only` replaces the config's active_checks and `strict=True` overrides the config's strict, as the CLI flags do.
    """
    active = list(dict.fromkeys(only or config.active_checks))
    _require_known(active, available)
    _require_known(config.check_options, available)
    # Options are validated for every available check, not just active ones, so a typo doesn't stay hidden until the check is turned on.
    options = {name: check.resolve_options(config.check_options.get(name, {})) for name, check in available.items()}
    if not active:
        raise ConfigError("No checks to run: active_checks is empty.")
    return Plan(
        target=config.target,
        strict=strict or config.strict,
        checks=[PlannedCheck(available[name], options[name], config.check_timeout_seconds) for name in active],
    )


def _require_known(names: Iterable[str], available: Mapping[str, Check]) -> None:
    missing = sorted(name for name in names if name not in available)
    if missing:
        raise ConfigError(f"Unknown checks: {', '.join(with_suggestion(name, available) for name in missing)}")
