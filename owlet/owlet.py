import asyncio
import inspect
import pkgutil
from collections import defaultdict
from importlib import import_module
from pathlib import Path

from rich import print

from owlet.check import Check, Result
from owlet.config import Config, Site, load_config


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
        results = defaultdict(list)

        async def worker(site: Site):
            checks_to_run = site.active_checks_overrides or self._active_checks
            results[site.url] = await self._run_checks(site.url, checks_to_run)

        async with asyncio.TaskGroup() as tg:
            for site in self._targets:
                tg.create_task(worker(site))

        for site in self._targets:
            print(f"\nResults for {site.url}:")
            for result in results[site.url]:
                print(f"  - {'[green]SUCCESS[/]' if result.success else '[red]FAILED[/]'}: {result.check_name}{':' if result.content else ''} {result.content}")

    async def _run_checks(self, url: str, checks: list[str]) -> list[Result]:
        results_by_check: dict[str, list[Result]] = {}

        async def worker(check_name: str):
            check = self._available_checks[check_name]
            results_by_check[check_name] = await check(url)

        async with asyncio.TaskGroup() as tg:
            for check_name in checks:
                tg.create_task(worker(check_name))

        results = []
        for check_name in checks:
            results.extend(results_by_check[check_name])
        return results

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