import asyncio

import httpx
from rich import print

from owlet.check import Check, Result, discover_checks
from owlet.config import Config, load_config
from owlet.context import Context


class Owlet:

    def __init__(self, config: Config | str):
        if isinstance(config, str):
            config = load_config(config)
        self._target: str = config.target
        self._active_checks: list[str] = list(set(config.active_checks))
        self._available_checks: dict[str, Check] = discover_checks()
        self._validate_required_checks_are_available(self._active_checks, self._available_checks)


    async def run(self):
        async with httpx.AsyncClient() as http_client:
            context = Context(target=self._target, http_client=http_client)
            results: list[Result] = []

            async def worker(check_name: str):
                results.extend(await self._available_checks[check_name].run(context))

            async with asyncio.TaskGroup() as tg:
                for check_name in self._active_checks:
                    tg.create_task(worker(check_name))

            for result in results:
                print(f"  {'[green]PASS[/]' if result.success else '[red]FAIL[/]'}: {result.label}{f': {result.content}' if result.content else ''}")

    def _validate_required_checks_are_available(self, required_checks : list[str], available_checks : dict[str, Check]):
        missing = [check for check in required_checks if check not in available_checks]
        if missing:
            raise ValueError(f"Unknown checks: {', '.join(sorted(missing))}")
