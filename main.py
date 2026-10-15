import asyncio
import sys
import tomllib

from rich import print

from owlet.owlet import ExitCode, Owlet


def main() -> ExitCode:
    try:
        owlet = Owlet("config.toml")
    except (OSError, tomllib.TOMLDecodeError, ValueError) as e:
        print(f"[red]Error:[/] {e}", file=sys.stderr)
        return ExitCode.USAGE_ERROR
    results = asyncio.run(owlet.run())
    return owlet.exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
