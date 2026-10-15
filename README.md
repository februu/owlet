<div align="center">

### 𝚘𝚠𝚕𝚎𝚝

_Owlet is a small async website health checker: availability, TLS, security headers, crawlability and broken links, configured from one TOML file._

⠀· · ─────── · 𖥸 · ─────── · ·

</div>

**Current features:**

- 8 built-in checks covering availability, TLS, security headers, crawlability and links
- Five result states: `PASS`, `WARN`, `FAIL`, `SKIP` and `ERROR`
- Per-check options, validated against each check's signature when the config loads
- Exit codes for CI and cron, with a `strict` mode that treats warnings as failures
- Checks run concurrently and share HTTP responses, so the same URL is never fetched twice in a run
- New checks are picked up automatically: write a function in `owlet/checks/` and decorate it with `@check`

**Upcoming features:**

- Simple CLI
- JSON output
- More checks: DNS and email records, cookie flags, exposed files, SEO basics

_Suggestions are welcome!_

## getting started

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

Create a `config.toml` in the directory you run owlet from (it's git-ignored):

```toml
target = "https://example.com"
active_checks = ["http_status", "ssl_certificate", "security_headers"]
```

Then run:

```sh
uv run main.py
```

Each result prints on its own line as `STATUS: check - detail: message`, in the order the checks are listed in `active_checks`.

## configuration

| Key | Type | Default | Description |
|---|---|---|---|
| `target` | string | `""` | URL of the site to check. |
| `active_checks` | list of strings | `[]` | Checks to run, in output order. Duplicates are ignored. |
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

Owlet validates the whole config before it sends any request. Unknown keys, unknown checks, unknown options and values of the wrong type all stop the run with a `Config error:` message and exit code 2. Options for checks that aren't in `active_checks` are validated too, so a typo doesn't stay hidden until you turn the check on.

## checks

| Check | What it verifies | Options (default) |
|---|---|---|
| `http_status` | The page responds with a 2xx status after following redirects. | |
| `response_time` | The page responds in time, including redirects. | `limit_seconds` (1.5) |
| `https_redirect` | The `http://` version of the site redirects to `https://`. | |
| `ssl_certificate` | The certificate verifies and isn't close to expiry. `FAIL` under `fail_days`, `WARN` under `warn_days`, `SKIP` for `http://` targets. | `fail_days` (14), `warn_days` (30) |
| `security_headers` | HSTS, CSP, `X-Content-Type-Options`, `Referrer-Policy` and clickjacking protection, one result per header. | |
| `robots_txt` | `/robots.txt` exists and isn't empty. | |
| `sitemap` | A sitemap is listed in `robots.txt` or served at `/sitemap.xml`. `WARN` if missing, `FAIL` if invalid. | |
| `broken_links` | Links and resources on the page don't return 4xx or 5xx. | `max_links` (50), `max_concurrent_requests` (10) |

## results and exit codes

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
| `2` | The config is missing or invalid. |

## writing a check

Add a function to any module in `owlet/checks/` and decorate it with `@check`. The function name becomes the check name.

```python
from owlet.check import Result, Status, check
from owlet.context import Context


@check
async def has_title(ctx: Context, *, min_length: int = 1) -> Result:
    """The page has a non-empty <title>."""
    response = await ctx.get(ctx.target)
    ...
    return Result(Status.PASS, "Found a title.")
```

- **Context:** the first parameter. `ctx.target` is the configured URL, and `ctx.get(url)` fetches a URL once per run and shares the response with every other check.
- **Options:** keyword-only parameters after `*`. Each one needs a default and a type annotation; the annotation is what owlet validates config values against. Supported types are `int`, `float`, `bool`, `str` and `list[...]`.
- **Results:** return one `Result`, return an iterable of them, or `yield` them from an async generator. Use `name=` to tell several results from one check apart, as `security_headers` does for each header.
- **Errors:** you don't need to catch network errors; they become `FAIL` automatically. Any other exception becomes `ERROR`.
- **Docstring:** stored as the check's description, so write it as a one-line summary of what passing means.

Checks can be `async def` (preferred), async generators, or plain functions. Plain functions run in a worker thread.
