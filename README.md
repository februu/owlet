<div align="center">

### 𝚘𝚠𝚕𝚎𝚝

_Owlet is a small async website health checker configured from one TOML file._

⠀· · ─────── · 𖥸 · ─────── · ·

</div>

**Current features:**

- 8 built-in checks covering availability, TLS, security headers, crawlability and links
- Five result states: `PASS`, `WARN`, `FAIL`, `SKIP` and `ERROR`
- Per-check options, validated against each check's signature when the config loads
- Exit codes for CI and cron, with a strict mode that treats warnings as failures
- Checks run concurrently and share GET responses, so a page several checks need is downloaded once
- New checks are picked up automatically: write a function in `owlet/checks/` and decorate it with `@check`
- A CLI to run checks, list them with their options, and generate a starter config

**Upcoming features:**

- JSON output
- More checks: DNS and email records, cookie flags, exposed files, SEO basics

_Suggestions are welcome!_

## Getting started

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

Generate a config for your site, then run it:

```sh
uv run owlet --init https://example.com > config.toml    # config.toml is git-ignored
uv run owlet config.toml
```

`--init` enables every check and lists every option, commented out at its default. Results print in the order the checks are listed in `active_checks`, followed by a count per status.

## Cli

```
usage: owlet [-h] [--version] [--only CHECK] [--strict] [-q] [--list-checks] [--init TARGET] [config]
```

Running `owlet` with no arguments shows the help.

| Option | Effect |
|---|---|
| `--only CHECK` | Runs only this check instead of `active_checks`. Repeat it for several: `--only sitemap --only robots_txt`. Any available check is allowed, not just active ones. |
| `--strict` | Treats warnings as failures, even if the config has `strict = false`. |
| `-q`, `--quiet` | Prints only results that fail the run (`FAIL`, `ERROR`, and `WARN` in strict mode), followed by the count per status. Prints nothing if no result fails, so cron only emails you about problems. |
| `--list-checks` | Lists every check with what it verifies and its options, read from the code. |
| `--init TARGET` | Prints a starter config for `TARGET` to stdout. |

## Configuration

| Key | Type | Default | Description |
|---|---|---|---|
| `target` | string | | Required. `http://` or `https://` URL of the site to check. |
| `active_checks` | list of strings | | Checks to run, in output order. Duplicates are ignored. Must list at least one check, unless you pass `--only`. |
| `strict` | bool | `false` | Treat `WARN` as a failure when deciding the exit code. |
| `checks.<name>` | table | | Options for one check. See [checks](#checks). |

```toml
target = "https://example.com"
strict = false
active_checks = ["response_time", "ssl_certificate", "broken_links"]

[checks.response_time]
limit_seconds = 0.8

[checks.ssl_certificate]
warn_days = 45
```

Owlet validates the whole config before it sends any request. Unknown keys, unknown checks, unknown options, values of the wrong type and option values a check can't use all stop the run with a `Config error:` message and exit code 2. Options for checks that aren't in `active_checks` are validated too, so a typo doesn't stay hidden until you turn the check on.

## Checks

| Check | What it verifies | Options (default) |
|---|---|---|
| `http_status` | The page responds with a 2xx status after following redirects. | |
| `response_time` | The page responds in time, including redirects. | `limit_seconds` (1.5) |
| `https_redirect` | The `http://` version of the site redirects to `https://`. | |
| `ssl_certificate` | The certificate verifies and isn't close to expiry. `FAIL` under `fail_days`, `WARN` under `warn_days`, `SKIP` for `http://` targets. | `fail_days` (14), `warn_days` (30) |
| `security_headers` | HSTS, CSP, `X-Content-Type-Options`, `Referrer-Policy` and clickjacking protection, one result per header. | |
| `robots_txt` | `/robots.txt` exists and isn't empty. `WARN` if missing or empty. | |
| `sitemap` | A sitemap is listed in `robots.txt` or served at `/sitemap.xml`. `WARN` if missing, `FAIL` if invalid. | |
| `broken_links` | Links and resources on the page don't return 4xx or 5xx. | `max_links` (50), `max_concurrent_requests` (10) |

## Results and exit codes

| Status | Meaning |
|---|---|
| `PASS` | The check passed. |
| `WARN` | Worth attention, but not a failure unless `strict = true`. |
| `FAIL` | The check found a problem with the site. Network errors reaching the site (timeouts, refused connections, TLS errors) count as `FAIL`. |
| `SKIP` | The check doesn't apply to this target, such as TLS checks on an `http://` site. Never fails a run. |
| `ERROR` | The check itself crashed or returned something invalid. This points at a bug in owlet, not the site. |

| Exit code | Meaning |
|---|---|
| `0` | No failures. Warnings and skips are allowed unless `strict = true`. |
| `1` | At least one `FAIL` or `ERROR`, or a `WARN` in strict mode. |
| `2` | Invalid command-line arguments, or a missing or invalid config. |

## Writing your own check

Add a function to any module in `owlet/checks/` and decorate it with `@check`. The function name becomes the check name.

```python
from owlet.check import Result, Status, check
from owlet.context import Context


@check
async def has_title(ctx: Context, *, min_length: int = 1) -> Result:
    """The page has a <title> of at least `min_length` characters."""
    response = await ctx.get(ctx.target)
    ...
    return Result(Status.PASS, "Found a title.")
```

- **Context:** the first parameter. `ctx.target` is the configured URL, and `ctx.get(url)` sends a GET once per run and shares the response with every other check. Requests made directly through `ctx.http_client` aren't shared.
- **Options:** keyword-only parameters after `*`, each with a default. Give them a type annotation too: owlet validates config values against it, for `int`, `float`, `bool`, `str` and `list[...]`. Options without an annotation, or with one owlet can't check (such as a union), accept any value.
- **Results:** return one `Result`, return an iterable of them, or `yield` them from an async generator. Use `name=` to tell several results from one check apart, as `security_headers` does for each header.
- **Errors:** you don't need to catch network errors; they become `FAIL` automatically. Any other exception becomes `ERROR`.
- **Option values:** owlet checks option types for you. To reject values of the right type that the check can't use, pass a `validate` function to `@check`. It takes every option as a keyword argument and raises `ConfigError` (from `owlet.config`) for a bad value. Owlet calls it when the config loads, so a bad value stops the run with `Config error:` and exit code 2, before any request is sent. The check itself can then assume its options are valid.

  ```python
  def _validate_has_title(*, min_length: int) -> None:
      if min_length < 1:
          raise ConfigError(f"min_length must be at least 1, got {min_length}.")


  @check(validate=_validate_has_title)
  async def has_title(ctx: Context, *, min_length: int = 1) -> Result:
      ...
  ```
- **Docstring:** shown by `owlet --list-checks`, so write it as a one-line summary of what passing means.

Checks can be `async def` (preferred), async generators, or plain functions. Plain functions run in a worker thread.
