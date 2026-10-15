import asyncio
from enum import IntEnum

import httpx
from rich import print

from owlet.check import Check, Result, Status, discover_checks
from owlet.config import Config, load_config
from owlet.context import Context


class ExitCode(IntEnum):
    """Process exit codes."""

    OK = 0
    """Every check passed, warned (outside strict mode) or was skipped."""
    CHECKS_FAILED = 1
    """At least one check failed or errored, or warned in strict mode."""
    USAGE_ERROR = 2
    """Owlet couldn't run: missing or invalid config, or an unknown check name."""


STATUS_STYLES = {
    Status.PASS: "green",
    Status.WARN: "yellow",
    Status.FAIL: "red",
    Status.SKIP: "dim",
    Status.ERROR: "bold magenta",
}


class Owlet:

    def __init__(self, config: Config | str):
        if isinstance(config, str):
            config = load_config(config)
        self._target: str = config.target
        self._strict: bool = config.strict
        self._active_checks: list[str] = list(dict.fromkeys(config.active_checks))
        self._available_checks: dict[str, Check] = discover_checks()
        self._validate_required_checks_are_available(self._active_checks, self._available_checks)


    async def run(self) -> list[Result]:
        async with httpx.AsyncClient() as http_client:
            context = Context(target=self._target, http_client=http_client)
            async with asyncio.TaskGroup() as tg:
                tasks = [tg.create_task(self._available_checks[name].run(context)) for name in self._active_checks]
            results: list[Result] = [result for task in tasks for result in task.result()]

            for result in results:
                status = f"[{STATUS_STYLES[result.status]}]{result.status}[/]"
                print(f"  {status}: {result.label}{f': {result.content}' if result.content else ''}")
            return results

    def exit_code(self, results: list[Result]) -> ExitCode:
        failing = {Status.FAIL, Status.ERROR} | ({Status.WARN} if self._strict else set())
        return ExitCode.CHECKS_FAILED if any(result.status in failing for result in results) else ExitCode.OK

    def _validate_required_checks_are_available(self, required_checks : list[str], available_checks : dict[str, Check]):
        missing = [check for check in required_checks if check not in available_checks]
        if missing:
            raise ValueError(f"Unknown checks: {', '.join(sorted(missing))}")
