import asyncio
from collections.abc import Mapping
from enum import IntEnum
from typing import Any

import httpx

from owlet.check import Check, Result, Status, discover_checks
from owlet.config import Config, ConfigError
from owlet.context import Context
from owlet.suggest import with_suggestion


class ExitCode(IntEnum):
    """Process exit codes."""

    OK = 0
    """Every check passed, warned (outside strict mode) or was skipped."""
    CHECKS_FAILED = 1
    """At least one check failed or errored, or warned in strict mode."""
    USAGE_ERROR = 2
    """Owlet couldn't run: invalid command-line arguments, or a missing or invalid config."""
    INTERNAL_ERROR = 3
    """Owlet itself crashed outside a check, e.g. a check module failed to import. A bug, not a problem with the site."""
    INTERRUPTED = 130
    """The run was cancelled with Ctrl+C."""


class Owlet:
    def __init__(self, config: Config, checks: Mapping[str, Check] | None = None):
        """`checks` are the checks available to run, by name; defaults to every discovered check."""
        self._target: str = config.target
        self._strict: bool = config.strict
        self._check_timeout: float = config.check_timeout_seconds
        self._active_checks: list[str] = list(dict.fromkeys(config.active_checks))
        self._available_checks: dict[str, Check] = dict(checks) if checks is not None else discover_checks()
        self._validate_required_checks_are_available(self._active_checks)
        self._check_options: dict[str, dict[str, Any]] = self._resolve_check_options(config.check_options)
        if not self._active_checks:
            # An empty run would always exit 0, hiding a broken config in CI.
            raise ConfigError("No checks to run: active_checks is empty.")

    async def run(self) -> list[Result]:
        async with httpx.AsyncClient() as http_client:
            context = Context(target=self._target, http_client=http_client)
            try:
                async with asyncio.TaskGroup() as tg:
                    tasks = [
                        tg.create_task(self._available_checks[name].run(context, self._check_options[name], self._check_timeout))
                        for name in self._active_checks
                    ]
            finally:
                await context.close()
            return [result for task in tasks for result in task.result()]

    def is_failure(self, result: Result) -> bool:
        """Whether this result fails the run: FAIL and ERROR always, WARN in strict mode."""
        return result.status in (Status.FAIL, Status.ERROR) or (self._strict and result.status is Status.WARN)

    def exit_code(self, results: list[Result]) -> ExitCode:
        return ExitCode.CHECKS_FAILED if any(self.is_failure(result) for result in results) else ExitCode.OK

    def _resolve_check_options(self, check_options: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        self._validate_required_checks_are_available(list(check_options))
        return {name: check.resolve_options(check_options.get(name, {})) for name, check in self._available_checks.items()}

    def _validate_required_checks_are_available(self, required_checks: list[str]):
        missing = [check for check in required_checks if check not in self._available_checks]
        if missing:
            raise ConfigError(f"Unknown checks: {', '.join(with_suggestion(name, self._available_checks) for name in sorted(missing))}")
