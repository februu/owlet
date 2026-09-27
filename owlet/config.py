import tomllib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Site:
    """Represents a site with a name and URL."""

    url: str
    active_checks_overrides: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class Config:
    """Configuration for the application."""

    active_checks: list[str]
    sites: list[Site]

def load_config(file_path: str) -> Config:
    """Load configuration from a TOML file."""
    with open(file_path, "rb") as f:
        data = tomllib.load(f)

    sites = [Site(**site) for site in data.get("sites", [])]
    return Config(
        active_checks=data.get("active_checks", []),
        sites=sites
    )
