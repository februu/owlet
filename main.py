import asyncio

from owlet.owlet import Owlet


def main():
    owlet = Owlet("config.toml")
    asyncio.run(owlet.run())


if __name__ == "__main__":
    main()
