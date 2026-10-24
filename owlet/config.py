import codecs
import os
import re
import tomllib
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from owlet.suggest import with_suggestion


class ConfigError(ValueError):
    """The config is invalid: unreadable file, bad TOML, unknown keys, checks or options, or values of the wrong type."""


DEFAULT_USER_AGENT = f"owlet/{version('owlet')}"


@dataclass(frozen=True)
class HttpConfig:
    """Settings for the HTTP client every check shares, from the [http] table."""

    timeout_seconds: float = 5.0
    """Timeout for each network operation: connecting, sending, waiting for data, and getting a pooled connection."""
    user_agent: str = DEFAULT_USER_AGENT
    """User-Agent sent with every request."""
    headers: dict[str, str] = field(default_factory=dict)
    """Extra headers, with ${NAME} environment variables expanded. Sent only to the target's host, and only over HTTPS for an
    https:// target, so tokens don't reach third-party links or travel unencrypted."""
    verify: bool = True
    """Verify TLS certificates on HTTP requests. ssl_certificate always verifies."""
    max_connections: int = 100
    """Most connections open at once, across all checks."""


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
    http: HttpConfig = field(default_factory=HttpConfig)
    """Settings for the HTTP client, from the [http] table."""


CHECK_TIMEOUT_KEY = "timeout_seconds"
"""Reserved in every [checks.<name>] table for that check's timeout, so no check may have an option by this name."""

KNOWN_KEYS = {"target", "active_checks", "strict", "check_timeout_seconds", "checks", "plugins", "http"}
KNOWN_HTTP_KEYS = {"timeout_seconds", "user_agent", "headers", "verify", "max_connections"}

HEADER_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
"""An HTTP header name: one or more token characters (RFC 9110)."""
HEADER_VALUE = re.compile(r"[\x20-\x7e\t]*")
"""A header value httpx can send: printable ASCII and tabs, so no line breaks that would start a new header."""
ENV_REFERENCE = re.compile(r"\$\$|\$\{([^}]*)\}")
"""`${NAME}` reads an environment variable in a header value; `$$` is a literal `$`."""
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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
        http=_http_config(data.get("http", {})),
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


def _http_config(data: Any) -> HttpConfig:
    """Validate the [http] table, expanding environment variables in header values."""
    if not isinstance(data, dict):
        raise ConfigError("'http' must be an [http] table.")
    unknown = sorted(data.keys() - KNOWN_HTTP_KEYS)
    if unknown:
        named = ", ".join(with_suggestion(key, KNOWN_HTTP_KEYS) for key in unknown)
        if "follow_redirects" in unknown:
            named += " (each check decides whether to follow redirects, so it can't be set for all of them)"
        raise ConfigError(f"Unknown key(s) in [http]: {named}.")

    defaults = HttpConfig()
    timeout_seconds = _positive_seconds(data.get("timeout_seconds", defaults.timeout_seconds), "http.timeout_seconds")

    user_agent = data.get("user_agent", defaults.user_agent)
    if not isinstance(user_agent, str) or not user_agent.strip() or not HEADER_VALUE.fullmatch(user_agent):
        raise ConfigError(f"'http.user_agent' must be a non-empty line of printable ASCII, got {user_agent!r}.")

    verify = data.get("verify", defaults.verify)
    if not isinstance(verify, bool):
        raise ConfigError(f"'http.verify' must be true or false, got {verify!r}.")

    max_connections = data.get("max_connections", defaults.max_connections)
    if isinstance(max_connections, bool) or not isinstance(max_connections, int) or max_connections < 1:
        raise ConfigError(f"'http.max_connections' must be a whole number of at least 1, got {max_connections!r}.")

    headers = data.get("headers", {})
    if not isinstance(headers, dict):
        raise ConfigError(f"'http.headers' must be a table of header names and values, got {headers!r}.")
    expanded = {}
    for name, value in headers.items():
        if not HEADER_NAME.fullmatch(name):
            raise ConfigError(f"'http.headers' has an invalid header name {name!r}.")
        if name.lower() == "user-agent":
            raise ConfigError("Set the User-Agent with 'http.user_agent' instead of in 'http.headers'.")
        if not isinstance(value, str):
            raise ConfigError(f"Header 'http.headers.{name}' must be a string, got {value!r}.")
        expanded[name] = _expand_env(value, f"http.headers.{name}")
        if not HEADER_VALUE.fullmatch(expanded[name]):
            raise ConfigError(f"Header 'http.headers.{name}' must be one line of printable ASCII, after expanding environment variables.")

    return HttpConfig(timeout_seconds, user_agent, expanded, verify, max_connections)


def _expand_env(value: str, key: str) -> str:
    """Replace each `${NAME}` in `value` with that environment variable and each `$$` with `$`; an unset variable is an error."""

    def replace(match: re.Match[str]) -> str:
        if match[0] == "$$":
            return "$"
        name = match[1]
        if not ENV_NAME.fullmatch(name):
            raise ConfigError(f"'{key}' has an invalid environment variable name {name!r} in '${{{name}}}'. Use $$ for a literal $.")
        if name not in os.environ:
            raise ConfigError(f"'{key}' uses the environment variable {name}, which isn't set.")
        return os.environ[name]

    return ENV_REFERENCE.sub(replace, value)


def _plugin_files(path: Path, entry: str) -> list[Path]:
    """The .py files a `plugins` entry stands for: the file itself, or every module in a folder except `_private.py` ones."""
    if path.is_dir():
        return sorted(file for file in path.glob("*.py") if not file.name.startswith("_"))
    if not path.is_file():
        raise ConfigError(f"Plugin '{entry}' not found at '{path}'. Plugin paths are relative to the config file.")
    if path.suffix != ".py":
        raise ConfigError(f"Plugin '{entry}' must be a .py file or a folder of them.")
    return [path]
