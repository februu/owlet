import difflib
from collections.abc import Iterable


def with_suggestion(name: str, choices: Iterable[str], *, match_on: str | None = None) -> str:
    """`name`, plus the closest of `choices` if one is close enough, e.g. `ssl-certificate (did you mean ssl_certificate?)`.

    `match_on` compares a different string than the one shown, e.g. `--jsn` for the argument `--jsn=1`.
    """
    matches = difflib.get_close_matches(match_on or name, list(choices), n=1)
    return f"{name} (did you mean {matches[0]}?)" if matches else name
