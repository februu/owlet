import asyncio
import inspect
import pkgutil
from importlib import import_module
from pathlib import Path

import httpx
from rich import print

from owlet.check import Check, Result
from owlet.config import Config, load_config
from owlet.context import Context


class Owlet:

    def __init__(self, config: Config | str):
        if isinstance(config, str):
            config = load_config(config)
        self._target: str = config.target
        self._active_checks: list[str] = list(set(config.active_checks))
        self._available_checks: dict[str, Check] = self._load_checks()
        self._validate_required_checks_are_available(self._active_checks, self._available_checks)


    async def run(self):
        async with httpx.AsyncClient() as http_client:
            context = Context(target=self._target, http_client=http_client)
            results: list[Result] = []

            async def worker(check_name: str):
                check = self._available_checks[check_name]
                try:
                    results.extend(await check(context))
                except Exception as e:  # noqa: BLE001
                    message = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                    results.extend([Result(check_name, False, message)])

            async with asyncio.TaskGroup() as tg:
                for check_name in self._active_checks:
                    tg.create_task(worker(check_name))

            print(f"\nResults for {self._target}:")
            for result in results:
                print(f"  {'[green]PASS[/]' if result.success else '[red]FAIL[/]'}: {result.check_name}{':' if result.content else ''} {result.content}")

    def _load_checks(self) -> dict[str, Check]:
        loaded_checks: dict[str, Check] = {}
        checks_directory = Path(__file__).parent / "checks"
        for module_info in pkgutil.iter_modules([str(checks_directory)]):
            module = import_module(f"owlet.checks.{module_info.name}")
            for name, func in inspect.getmembers(module, inspect.isfunction):
                if inspect.getmodule(func) is module and not name.startswith("_"):
                    loaded_checks[name] = func
        return loaded_checks

    def _validate_required_checks_are_available(self, required_checks : list[str], available_checks : dict[str, Check]):
        missing = [check for check in required_checks if check not in available_checks]
        if missing:
            raise ValueError(f"Unknown checks: {', '.join(sorted(missing))}")