import tomllib
from dataclasses import dataclass, field
from typing import Any


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


def load_config(file_path: str) -> Config:
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
    check_options = data.get("checks", {})
    for name, options in check_options.items():
        if not isinstance(options, dict):
            raise ConfigError(f"Options for check '{name}' must be a [checks.{name}] table.")

    return Config(
        target=data.get("target", ""),
        active_checks=data.get("active_checks", []),
        strict=data.get("strict", False),
        check_options=check_options,
    )
