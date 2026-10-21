import argparse
import asyncio
import inspect
import json
import sys
import time
import traceback
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import metadata
from itertools import groupby
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from owlet.check import Check, Result, Status, discover_checks
from owlet.config import Config, ConfigError, load_config
from owlet.owlet import ExitCode, Owlet
from owlet.suggest import with_suggestion

STATUS_STYLES = {
    Status.PASS: "green",
    Status.WARN: "yellow",
    Status.FAIL: "red",
    Status.SKIP: "dim",
    Status.ERROR: "magenta",
}

console = Console()
if not console.is_terminal:
    # Piped or in CI, rich falls back to 80 columns and wraps or crops long lines. Let lines run to their full length instead.
    console = Console(width=1_000_000)


def _print_table(table: Table) -> None:
    if console.is_terminal:
        console.print(table)
        return
    with console.capture() as capture:
        console.print(table)
    print("\n".join(line.rstrip() for line in capture.get().splitlines()))


def build_parser() -> argparse.ArgumentParser:
    package = metadata("owlet")
    parser = argparse.ArgumentParser(prog=package["Name"], description=package["Summary"], color=False)
    parser.add_argument("config", nargs="?", type=Path, help="config file to run")
    parser.add_argument("--version", action="version", version=f"%(prog)s {package['Version']}")
    parser.add_argument("--only", action="append", metavar="CHECK", help="run only this check; repeat this option for several checks")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures, overriding the config file setting")
    parser.add_argument("-v", "--verbose", action="store_true", help="print the traceback under each ERROR result")
    parser.add_argument("-q", "--quiet", action="store_true", help="print only results that fail the run, and nothing if none do")
    parser.add_argument("--json", action="store_true", help="print results as JSON instead of a table")
    parser.add_argument("--list-checks", action="store_true", help="list available checks and their options")
    parser.add_argument("--init", metavar="TARGET", help="print a starter config for TARGET")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return ExitCode.INTERRUPTED
    except Exception:  # noqa: BLE001 - any crash must map to INTERNAL_ERROR, not Python's default exit code 1
        traceback.print_exc()
        print("\nInternal error: owlet or one of its checks crashed. This is a bug, not a problem with the site.", file=sys.stderr)
        return ExitCode.INTERNAL_ERROR


def _main(argv: list[str] | None) -> int:
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)
    _validate(parser, args, unknown)

    if args.list_checks:
        return _list_checks()
    if args.init is not None:
        print(_starter_config(args.init, list(discover_checks().values())), end="")
        return ExitCode.OK
    if args.config is None:
        parser.print_help()
        return ExitCode.OK
    return _run(args.config, args.only, args.strict, args.quiet, args.verbose, args.json)


def _validate(parser: argparse.ArgumentParser, args: argparse.Namespace, unknown: list[str]) -> None:
    """Reject input argparse can't catch on its own, with errors that say what to type instead."""
    if args.config and not args.config.exists() and str(args.config) in ("init", "list-checks"):
        parser.error(f"'{args.config}' is not a config file. Did you mean --{args.config}?")
    if unknown:
        flags = [flag for action in parser._actions for flag in action.option_strings]
        named = [with_suggestion(arg, flags, match_on=arg.partition("=")[0]) if arg.startswith("-") else arg for arg in unknown]
        parser.error(f"unrecognized arguments: {', '.join(named)}")
    if args.init is not None and not args.init.strip():
        parser.error("--init needs a TARGET URL")
    modes = [flag for flag, used in (("--list-checks", args.list_checks), ("--init", args.init is not None)) if used]
    if len(modes) > 1:
        parser.error("--list-checks and --init can't be used together")
    if modes and args.config:
        hint = " Redirect its output instead: owlet --init TARGET > config.toml" if args.init is not None else ""
        parser.error(f"{modes[0]} doesn't take a config file.{hint}")
    if not args.config and (args.only or args.strict or args.quiet or args.verbose or args.json):
        parser.error("--only, --strict, --quiet, --verbose and --json need a config file to run")


def _run(config: Path, only: list[str] | None, strict: bool, quiet: bool, verbose: bool, as_json: bool) -> ExitCode:
    try:
        settings = load_config(config)
        settings = replace(
            settings,
            active_checks=only or settings.active_checks,
            strict=strict or settings.strict,
        )
        owlet = Owlet(settings)
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return ExitCode.USAGE_ERROR

    started_at = datetime.now(UTC)
    started = time.perf_counter()
    results = asyncio.run(owlet.run())
    duration = time.perf_counter() - started
    exit_code = owlet.exit_code(results)
    shown = [result for result in results if owlet.is_failure(result)] if quiet else results
    if as_json:
        print(_results_json(settings, owlet, shown, results, exit_code, started_at, duration))
    elif shown:
        _print_results(shown, results, duration, verbose)
    return exit_code


def _list_checks() -> ExitCode:
    table = Table.grid(padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column()
    for group, checks in groupby(discover_checks().values(), key=_group):
        table.add_row("", "")
        table.add_row(f"== {group} ==", "")
        for check in checks:
            table.add_row(check.name, Text(check.description or ""))
            for name, param in check.options.items():
                option = f"{name}: {inspect.formatannotation(param.annotation)} = {param.default!r}"
                table.add_row("", Text(option, style="dim"))
    _print_table(table)
    console.print()
    return ExitCode.OK


def _group(check: Check) -> str:
    """The check's module name, e.g. `tls` for owlet.checks.tls."""
    return check.func.__module__.rpartition(".")[2]


def _print_results(shown: list[Result], results: list[Result], duration: float, verbose: bool) -> None:
    """Print the `shown` results as a table, then a count per status across all `results`. `verbose` adds tracebacks."""
    table = Table.grid(padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column()
    for result in shown:
        text = Text("\n".join([result.summary, *(f"  {line}" for line in result.details)]))
        if verbose and result.traceback:
            text.append("\n" + "\n".join(f"  {line}" for line in result.traceback.splitlines()), style="dim")
        table.add_row(Text(result.status, style=STATUS_STYLES[result.status]), Text(result.label), text)
    _print_table(table)

    counts = Counter(result.status for result in results)
    print("\n" + ", ".join(f"{counts[status]} {status.lower()}" for status in Status if counts[status]) + f" in {duration:.2f}s")


def _results_json(
    settings: Config, owlet: Owlet, shown: list[Result], results: list[Result], exit_code: ExitCode, started_at: datetime, duration: float
) -> str:
    """The `shown` results as JSON, with a count per status across all `results`."""
    counts = Counter(result.status for result in results)
    return json.dumps(
        {
            "owlet_version": metadata("owlet")["Version"],
            "target": settings.target,
            "strict": settings.strict,
            "started_at": started_at.isoformat(timespec="seconds"),
            "duration_seconds": round(duration, 3),
            "exit_code": int(exit_code),
            "summary": {status: counts[status] for status in Status},
            "results": [
                {
                    "check": result.check_name,
                    "name": result.name,
                    "status": result.status,
                    "summary": result.summary,
                    "details": list(result.details),
                    "data": result.data,
                    "duration_seconds": round(result.duration_seconds, 3) if result.duration_seconds is not None else None,
                    "fails_run": owlet.is_failure(result),
                    "traceback": result.traceback,
                }
                for result in shown
            ],
        },
        indent=2,
        allow_nan=False,
    )


def _starter_config(target: str, checks: list[Check]) -> str:
    lines = [
        f"target = {json.dumps(target)}",
        "",
        "# Treat warnings as failures when deciding the exit code.",
        "strict = false",
        "",
        "# How long one check may run before it's stopped and reported as FAIL.",
        "check_timeout_seconds = 30.0",
        "",
        "active_checks = [",
    ]
    for group, group_checks in groupby(checks, key=_group):
        lines.append(f"    # {group}")
        lines.extend(f'    "{check.name}",' for check in group_checks)
    lines += ["]", "", "# Per-check options. Uncomment a table and a line to change a default."]
    for check in checks:
        if check.options:
            lines += ["", f"# [checks.{check.name}]"]
            lines.extend(f"# {name} = {json.dumps(param.default)}" for name, param in check.options.items())
    return "\n".join(lines) + "\n"
