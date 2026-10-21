import importlib.util
import pkgutil
import sys
from collections.abc import Sequence
from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path

from owlet.check import Check, registry
from owlet.config import ConfigError

CHECKS_PACKAGE = "owlet.checks"
ENTRY_POINT_GROUP = "owlet.checks"
"""Installed packages add checks by naming a module in this entry point group; importing it registers its checks."""
PLUGIN_PACKAGE = "owlet_plugins"
"""Plugin files from the config are imported as `owlet_plugins.<file stem>`."""


def discover_checks(plugins: Sequence[Path] = ()) -> dict[str, Check]:
    """Import the built-in checks, installed plugin packages and the `plugins` files so their @check decorators run.

    Returns every registered check, built-in ones first. Raises ConfigError for plugin files that can't be imported side by side.
    """
    for module_info in pkgutil.iter_modules(import_module(CHECKS_PACKAGE).__path__):
        import_module(f"{CHECKS_PACKAGE}.{module_info.name}")
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        try:
            entry_point.load()
        except Exception as e:
            raise RuntimeError(f"Plugin '{entry_point.name}' ({entry_point.value}) failed to import: {e}") from e
    for path in plugins:
        _import_file(path)
    return registry.checks


def _import_file(path: Path) -> None:
    name = f"{PLUGIN_PACKAGE}.{path.stem}"
    if existing := sys.modules.get(name):
        if Path(existing.__file__ or "").resolve() == path.resolve():
            return  # Already imported, e.g. by an earlier call; importing again would register its checks twice.
        raise ConfigError(f"Plugin files '{existing.__file__}' and '{path}' have the same name; rename one.")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ConfigError(f"Can't import plugin file '{path}'.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
