import tomllib
from dataclasses import dataclass, field
from typing import Any


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
    with open(file_path, "rb") as f:
        data = tomllib.load(f)

    unknown = sorted(data.keys() - KNOWN_KEYS)
    if unknown:
        raise ValueError(f"Unknown config key(s): {', '.join(unknown)}.")
    check_options = data.get("checks", {})
    for name, options in check_options.items():
        if not isinstance(options, dict):
            raise ValueError(f"Options for check '{name}' must be a [checks.{name}] table.")

    return Config(
        target=data.get("target", ""),
        active_checks=data.get("active_checks", []),
        strict=data.get("strict", False),
        check_options=check_options,
    )
