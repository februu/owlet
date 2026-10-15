import asyncio
import sys

from rich import print
from rich.markup import escape

from owlet.config import ConfigError
from owlet.owlet import ExitCode, Owlet


def main() -> ExitCode:
    try:
        owlet = Owlet("config.toml")
    except ConfigError as e:
        print(f"[red]Config error:[/] {escape(str(e))}", file=sys.stderr)
        return ExitCode.USAGE_ERROR
    results = asyncio.run(owlet.run())
    return owlet.exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
