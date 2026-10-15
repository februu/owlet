import tomllib
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Configuration for the application."""

    target: str
    """The target URL or IP address to check."""
    active_checks: list[str]
    """List of checks to run."""
    strict: bool = False
    """Treat warnings as failures when deciding the exit code."""


def load_config(file_path: str) -> Config:
    """Load configuration from a TOML file."""
    with open(file_path, "rb") as f:
        data = tomllib.load(f)

    return Config(
        target=data.get("target", ""),
        active_checks=data.get("active_checks", []),
        strict=data.get("strict", False),
    )
