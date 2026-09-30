import tomllib
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Configuration for the application."""

    target: str
    active_checks: list[str]
    

def load_config(file_path: str) -> Config:
    """Load configuration from a TOML file."""
    with open(file_path, "rb") as f:
        data = tomllib.load(f)

    return Config(
        target=data.get("target", ""),
        active_checks=data.get("active_checks", []),
    )
