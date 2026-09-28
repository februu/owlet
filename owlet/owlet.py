import asyncio
import inspect
import pkgutil
from collections import defaultdict
from importlib import import_module
from pathlib import Path

import httpx
from rich import print

from owlet.check import Check, Result
from owlet.config import Config, Site, load_config
from owlet.context import Context


class Owlet:

    def __init__(self, config: Config | str):
        if isinstance(config, str):
            config = load_config(config)
        self._targets: list[Site] = config.sites
        self._active_checks: list[str] = config.active_checks
        self._available_checks: dict[str, Check] = self._load_checks()
        required_checks = set([check for site in self._targets for check in site.active_checks_overrides] + self._active_checks)
        self._validate_required_checks_are_available(required_checks, self._available_checks)


    async def run(self):
        async with httpx.AsyncClient() as http_client:
            context = Context(http_client=http_client)
            results: dict[str, list[Result]] = defaultdict(list)

            async def worker(site: Site, check_name: str):
                check = self._available_checks[check_name]
                results[site.url].extend(await check(context, site.url))

            async with asyncio.TaskGroup() as tg:
                for site in self._targets:
                    checks_to_run = site.active_checks_overrides or self._active_checks
                    for check_name in checks_to_run:
                        tg.create_task(worker(site, check_name))

        for site in self._targets:
            print(f"\nResults for {site.url}:")
            for result in results[site.url]:
                print(f"  {'[green]PASS[/]' if result.success else '[red]FAIL[/]'}: {result.check_name}{':' if result.content else ''} {result.content}")

    def _load_checks(self) -> dict[str, Check]:
        loaded_checks: dict[str, Check] = {}
        checks_directory = Path(__file__).parent / "checks"
        for module_info in pkgutil.iter_modules([str(checks_directory)]):
            module = import_module(f"owlet.checks.{module_info.name}")
            for name, func in inspect.getmembers(module, inspect.isfunction):
                if inspect.getmodule(func) is module:
                    loaded_checks[name] = func
        return loaded_checks

    def _validate_required_checks_are_available(self, required_checks : set[str], available_checks : dict[str, Check]):
        missing = required_checks - available_checks.keys()
        if missing:
            raise ValueError(f"Unknown checks: {', '.join(sorted(missing))}")