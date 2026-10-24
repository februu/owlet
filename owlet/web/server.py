"""The web control panel: serves the frontend built from web/ and a small JSON API to list checks and run them."""

import argparse
import asyncio
import inspect
import json
import sys
import time
import traceback
from collections import Counter
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import metadata
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from owlet.check import Check, Result, Status
from owlet.config import CHECK_TIMEOUT_KEY, Config, ConfigError, load_config, parse_config
from owlet.discover import check_group, discover_checks
from owlet.owlet import ExitCode, Owlet
from owlet.plan import resolve

STATIC_DIR = Path(__file__).parent / "static"
"""Where `bun run build` in web/ puts the frontend."""


def create_app(
    config: Config | None, config_path: Path | None, available: Mapping[str, Check], *, trusted_hosts: list[str] | None = None
) -> Starlette:
    """The panel's app. `config`, if given, prefills the panel and supplies what the browser never sends: plugins and HTTP headers.

    `trusted_hosts` limits the Host header the app answers to, against DNS rebinding.
    """

    async def info(request: Request) -> Response:
        return JSONResponse(
            {
                "version": metadata("owlet")["Version"],
                "config_path": str(config_path) if config_path else None,
                "checks": [_check_json(check) for check in available.values()],
                "settings": _settings_json(config, available),
                "defaults": _settings_json(None, available),
                # Header values may hold secrets, so the panel only learns which headers the config sends.
                "header_names": sorted(config.http.headers) if config else [],
            }
        )

    async def run(request: Request) -> Response:
        # Requiring JSON makes a cross-site form or fetch need a CORS preflight, which this server never allows.
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            return _error("Send the settings as application/json.", 415)
        try:
            data = await request.json()
        except ValueError:
            return _error("The request body isn't valid JSON.")
        try:
            owlet = Owlet(resolve(_request_config(data, config), available))
        except ConfigError as e:
            return _error(str(e))
        return StreamingResponse(_stream(owlet), media_type="application/x-ndjson")

    routes = [Route("/api/info", info), Route("/api/run", run, methods=["POST"])]
    if STATIC_DIR.is_dir():
        routes.append(Mount("/", StaticFiles(directory=STATIC_DIR, html=True)))
    else:
        routes.append(Route("/", _not_built))
    middleware = [Middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)] if trusted_hosts else []
    return Starlette(routes=routes, middleware=middleware)


def _request_config(data: Any, base: Config | None) -> Config:
    """The browser's settings, in the shape of a TOML config, validated like one. Plugins and headers come from `base` only.

    Plugins import Python files, so a page in the browser mustn't be able to choose them.
    """
    if not isinstance(data, dict):
        raise ConfigError("Settings must be a JSON object.")
    if "plugins" in data:
        raise ConfigError("Plugins can only be set in the config file the panel was started with.")
    if isinstance(data.get("http"), dict) and "headers" in data["http"]:
        raise ConfigError("HTTP headers can only be set in the config file the panel was started with.")
    config = parse_config(data, Path.cwd())
    if base is None:
        return config
    return replace(config, plugins=base.plugins, http=replace(config.http, headers=base.http.headers))


async def _stream(owlet: Owlet) -> AsyncIterator[str]:
    """Run `owlet` and stream it as NDJSON: a `start` event, a `check` event as each check finishes, then `done` (or `error`)."""
    queue: asyncio.Queue[list[Result] | None] = asyncio.Queue()
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    yield _event(
        "start",
        target=owlet.plan.target,
        strict=owlet.plan.strict,
        checks=[planned.check.name for planned in owlet.plan.checks],
        started_at=started_at.isoformat(timespec="seconds"),
    )
    task = asyncio.create_task(owlet.run(queue.put_nowait))
    task.add_done_callback(lambda _: queue.put_nowait(None))
    try:
        while (results := await queue.get()) is not None:
            yield _event("check", check=results[0].check_name, results=[owlet.result_json(result) for result in results])
        try:
            results = task.result()
        except Exception:  # noqa: BLE001 - reported to the panel like the CLI's internal error, instead of cutting the stream
            yield _event("error", error=traceback.format_exc())
            return
        counts = Counter(result.status for result in results)
        yield _event(
            "done",
            exit_code=int(owlet.exit_code(results)),
            duration_seconds=round(time.perf_counter() - started, 3),
            summary={status: counts[status] for status in Status},
        )
    finally:
        # The browser went away or stopped the run: don't leave checks running.
        task.cancel()


def _event(type: str, **fields: Any) -> str:
    return json.dumps({"type": type, **fields}, allow_nan=False) + "\n"


def _error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _check_json(check: Check) -> dict[str, Any]:
    return {
        "name": check.name,
        "group": check_group(check),
        "description": check.description,
        "options": [
            {"name": name, "type": inspect.formatannotation(param.annotation), "default": param.default}
            for name, param in check.options.items()
        ],
    }


def _settings_json(config: Config | None, available: Mapping[str, Check]) -> dict[str, Any]:
    """Settings in the shape `/api/run` takes: `config`'s, or with no config, every check with default options."""
    if config is None:
        config = Config(target="", active_checks=list(available))
    names = config.check_options.keys() | config.check_timeouts.keys()
    return {
        "target": config.target,
        "active_checks": config.active_checks,
        "strict": config.strict,
        "check_timeout_seconds": config.check_timeout_seconds,
        "checks": {name: _check_table(config, name) for name in sorted(names)},
        "http": {
            "timeout_seconds": config.http.timeout_seconds,
            "user_agent": config.http.user_agent,
            "verify": config.http.verify,
            "max_connections": config.http.max_connections,
        },
    }


def _check_table(config: Config, name: str) -> dict[str, Any]:
    """The [checks.<name>] table: the check's options, plus its timeout_seconds if set."""
    table = dict(config.check_options.get(name, {}))
    if name in config.check_timeouts:
        table[CHECK_TIMEOUT_KEY] = config.check_timeouts[name]
    return table


async def _not_built(request: Request) -> Response:
    return PlainTextResponse(
        "The control panel's frontend isn't built yet. Build it with `bun install && bun run build` in the web/ folder, "
        "or run `bun run dev` there for development.",
        status_code=503,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="owlet-web", description="Run owlet's web control panel.", color=False)
    parser.add_argument("config", nargs="?", type=Path, help="config file to prefill the panel with, and to take plugins and headers from")
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default: %(default)s)")
    parser.add_argument("--port", type=int, default=8765, help="port to listen on (default: %(default)s)")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config) if args.config else None
        available = discover_checks(config.plugins if config else ())
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return ExitCode.USAGE_ERROR

    local = _is_loopback(args.host)
    # On a local address, only answer to local names, so other websites can't reach the API through DNS rebinding.
    app = create_app(config, args.config, available, trusted_hosts=["localhost", "127.0.0.1"] if local else None)
    if not local:
        print(f"Warning: listening on {args.host}. Anyone who can reach it can run checks against any URL from this machine.")
    print(f"Owlet control panel: http://{'localhost' if local else args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return ExitCode.OK


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False
