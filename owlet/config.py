import codecs
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from owlet.suggest import with_suggestion


class ConfigError(ValueError):
    """The config is invalid: unreadable file, bad TOML, unknown keys, checks or options, or values of the wrong type."""


@dataclass(frozen=True)
class Config:
    """Configuration for the application."""

    target: str
    """The http:// or https:// URL to check."""
    active_checks: list[str]
    """List of checks to run."""
    strict: bool = False
    """Treat warnings as failures when deciding the exit code."""
    check_timeout_seconds: float = 30.0
    """How long one check may run before it's stopped and reported as FAIL."""
    check_options: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Per-check options from the [checks.<name>] tables, keyed by check name, without `timeout_seconds`."""
    check_timeouts: dict[str, float] = field(default_factory=dict)
    """Per-check `timeout_seconds` from the [checks.<name>] tables, overriding check_timeout_seconds for that check."""
    plugins: list[Path] = field(default_factory=list)
    """Python files with extra checks to import, from `plugins` with folders expanded to the modules inside them."""


CHECK_TIMEOUT_KEY = "timeout_seconds"
"""Reserved in every [checks.<name>] table for that check's timeout, so no check may have an option by this name."""

KNOWN_KEYS = {"target", "active_checks", "strict", "check_timeout_seconds", "checks", "plugins"}


def load_config(file_path: Path) -> Config:
    """Load configuration from a TOML file."""
    try:
        raw = Path(file_path).read_bytes()
    except OSError as e:
        raise ConfigError(f"Can't read config file '{file_path}': {e.strerror}.") from e
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        # Windows PowerShell 5.1 writes redirected output (`owlet --init ... > config.toml`) as UTF-16.
        raise ConfigError(
            f"'{file_path}' is saved as UTF-16, but TOML files must be UTF-8. "
            "Windows PowerShell 5.1 does this when you redirect with `>`. Re-save the file as UTF-8, "
            "or create it with: owlet --init TARGET | Out-File -Encoding utf8 config.toml"
        )
    try:
        data = tomllib.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as e:
        raise ConfigError(f"'{file_path}' isn't valid UTF-8 (byte {e.start}). TOML files must be UTF-8.") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in '{file_path}': {e}.") from e

    unknown = sorted(data.keys() - KNOWN_KEYS)
    if unknown:
        raise ConfigError(f"Unknown config key(s): {', '.join(with_suggestion(key, KNOWN_KEYS) for key in unknown)}.")

    target = validate_target(data.get("target"))

    active_checks = data.get("active_checks", [])
    if not isinstance(active_checks, list) or not all(isinstance(name, str) for name in active_checks):
        raise ConfigError(f"'active_checks' must be a list of check names, got {active_checks!r}.")

    strict = data.get("strict", False)
    if not isinstance(strict, bool):
        raise ConfigError(f"'strict' must be true or false, got {strict!r}.")

    check_timeout_seconds = _positive_seconds(data.get("check_timeout_seconds", Config.check_timeout_seconds), "check_timeout_seconds")

    check_options = data.get("checks", {})
    if not isinstance(check_options, dict):
        raise ConfigError("'checks' must be a table of [checks.<name>] tables.")
    check_timeouts = {}
    for name, options in check_options.items():
        if not isinstance(options, dict):
            raise ConfigError(f"Options for check '{name}' must be a [checks.{name}] table.")
        if CHECK_TIMEOUT_KEY in options:
            check_timeouts[name] = _positive_seconds(options.pop(CHECK_TIMEOUT_KEY), f"checks.{name}.{CHECK_TIMEOUT_KEY}")

    plugins = data.get("plugins", [])
    if not isinstance(plugins, list) or not all(isinstance(path, str) for path in plugins):
        raise ConfigError(f"'plugins' must be a list of paths to .py files or folders, got {plugins!r}.")

    return Config(
        target=target,
        active_checks=active_checks,
        strict=strict,
        check_timeout_seconds=check_timeout_seconds,
        check_options=check_options,
        check_timeouts=check_timeouts,
        plugins=[file for path in plugins for file in _plugin_files(Path(file_path).parent / path, path)],
    )


def validate_target(target: Any, key: str = "'target'") -> str:
    """Return `target` if it's a usable http:// or https:// URL, else raise ConfigError naming it as `key`."""
    if target is None:
        raise ConfigError(f"{key} must be set to the URL of the site to check.")
    if not isinstance(target, str) or not target.strip():
        raise ConfigError(f"{key} must be the URL of the site to check, got {target!r}.")
    if target != target.strip():
        raise ConfigError(f"{key} must not start or end with whitespace, got {target!r}.")
    parts = urlsplit(target)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError(f"{key} must be an http:// or https:// URL, got {target!r}.")
    return target


def _positive_seconds(value: Any, key: str) -> float:
    # bool is a subclass of int, but `true` for a number is almost certainly a mistake.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        raise ConfigError(f"'{key}' must be a number greater than 0, got {value!r}.")
    return float(value)


def _plugin_files(path: Path, entry: str) -> list[Path]:
    """The .py files a `plugins` entry stands for: the file itself, or every module in a folder except `_private.py` ones."""
    if path.is_dir():
        return sorted(file for file in path.glob("*.py") if not file.name.startswith("_"))
    if not path.is_file():
        raise ConfigError(f"Plugin '{entry}' not found at '{path}'. Plugin paths are relative to the config file.")
    if path.suffix != ".py":
        raise ConfigError(f"Plugin '{entry}' must be a .py file or a folder of them.")
    return [path]
