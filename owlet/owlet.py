import inspect
import pkgutil
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


    def run(self):
        for site in self._targets:
            if not site.active_checks_overrides:
                 results = self._run_checks(site.url, self._active_checks)
            else:
                results = self._run_checks(site.url, site.active_checks_overrides)
            print(f"\nResults for {site.url}:")
            for result in results:
                print(f"  - {'[green]SUCCESS[/]' if result.success else '[red]FAILED[/]'}: {result.check_name}{':' if result.content else ''} {result.content}")

    def _run_checks(self, url: str, checks: list[str]) -> list[Result]:
        results = []
        for check_name in checks:
            check = self._available_checks[check_name]
            results.extend(check(url))
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