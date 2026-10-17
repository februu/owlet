import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """The config is invalid: unreadable file, bad TOML, unknown keys, checks or options, or values of the wrong type."""


@dataclass(frozen=True)
class Config:
    """Configuration for the application."""

    target: str
    """The target URL or IP address to check."""
    active_checks: list[str]
    """List of checks to run."""
    strict: bool = False
    """Treat warnings as failures when deciding the exit code."""
    check_options: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Per-check options from the [checks.<name>] tables, keyed by check name."""


KNOWN_KEYS = {"target", "active_checks", "strict", "checks"}


def load_config(file_path: Path) -> Config:
    """Load configuration from a TOML file."""
    try:
        with open(file_path, "rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise ConfigError(f"Can't read config file '{file_path}': {e.strerror}.") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in '{file_path}': {e}.") from e

    unknown = sorted(data.keys() - KNOWN_KEYS)
    if unknown:
        raise ConfigError(f"Unknown config key(s): {', '.join(unknown)}.")

    target = data.get("target")
    if not isinstance(target, str) or not target.strip():
        raise ConfigError("'target' must be set to the URL of the site to check.")
    parts = urlsplit(target)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError(f"'target' must be an http:// or https:// URL, got {target!r}.")

    active_checks = data.get("active_checks", [])
    if not isinstance(active_checks, list) or not all(isinstance(name, str) for name in active_checks):
        raise ConfigError(f"'active_checks' must be a list of check names, got {active_checks!r}.")

    strict = data.get("strict", False)
    if not isinstance(strict, bool):
        raise ConfigError(f"'strict' must be true or false, got {strict!r}.")

    check_options = data.get("checks", {})
    if not isinstance(check_options, dict):
        raise ConfigError("'checks' must be a table of [checks.<name>] tables.")
    for name, options in check_options.items():
        if not isinstance(options, dict):
            raise ConfigError(f"Options for check '{name}' must be a [checks.{name}] table.")

    return Config(
        target=target,
        active_checks=active_checks,
        strict=strict,
        check_options=check_options,
    )
