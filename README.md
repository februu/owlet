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
- Plugins: load checks from your own `.py` files listed in the config, or from installed packages
- A CLI to run checks, list them with their options, and generate a starter config
- JSON output for scripts and dashboards

**Upcoming features:**

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

In Windows PowerShell 5.1, `>` saves the file as UTF-16, which owlet rejects because TOML must be UTF-8. Use `uv run owlet --init https://example.com | Out-File -Encoding utf8 config.toml` there instead. PowerShell 7 and other shells save UTF-8 already.

`--init` enables every check and lists every option, commented out at its default. Results print in the order the checks are listed in `active_checks`, followed by a count per status.

## Cli

```
usage: owlet [-h] [--version] [--only CHECK] [--strict] [-v] [-q] [--json] [--list-checks] [--init TARGET] [config]
```

Running `owlet` with no arguments shows the help.

| Option | Effect |
|---|---|
| `--only CHECK` | Runs only this check instead of `active_checks`. Repeat it for several: `--only sitemap --only robots_txt`. Any available check is allowed, not just active ones. |
| `--strict` | Treats warnings as failures, even if the config has `strict = false`. |
| `-v`, `--verbose` | Prints the traceback under each `ERROR` result, to debug the check that crashed. `--json` always includes it. |
| `-q`, `--quiet` | Prints only results that fail the run (`FAIL`, `ERROR`, and `WARN` in strict mode). If any result fails, the count per status follows them. If none fail, it prints nothing at all, not even the counts, so cron only emails you about problems. With `--json`, it always prints the document, with an empty `results` array if none fail. |
| `--json` | Prints results as JSON instead of a table. See [JSON output](#json-output). With `--quiet`, `results` lists only the failing results. |
| `--list-checks` | Lists every check with what it verifies and its options, read from the code. Pass a config file too (`owlet --list-checks config.toml`) to include the checks from its `plugins`. |
| `--init TARGET` | Prints a starter config for `TARGET` to stdout. |

## Configuration

| Key | Type | Default | Description |
|---|---|---|---|
| `target` | string | | Required. `http://` or `https://` URL of the site to check. |
| `active_checks` | list of strings | | Checks to run, in output order. Duplicates are ignored. Must list at least one check, unless you pass `--only`. |
| `strict` | bool | `false` | Treat `WARN` as a failure when deciding the exit code. |
| `check_timeout_seconds` | number | `30.0` | How long one check may run. A check still running after this is stopped and reported as `FAIL` with `Timed out after Ns.`, and the other checks carry on. |
| `checks.<name>` | table | | Options for one check. See [checks](#checks). |
| `plugins` | list of strings | `[]` | `.py` files, or folders of them, with extra checks. Paths are relative to the config file. See [plugins](#plugins). |

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
| `FAIL` | The check found a problem with the site. Network errors reaching the site (timeouts, refused connections, TLS errors) count as `FAIL`, and so does a check that runs longer than `check_timeout_seconds`. |
| `SKIP` | The check doesn't apply to this target, such as TLS checks on an `http://` site. Never fails a run. |
| `ERROR` | The check itself crashed or returned something invalid. This points at a bug in owlet, not the site. Run with `--verbose` to see the traceback. |

| Exit code | Meaning |
|---|---|
| `0` | No failures. Warnings and skips are allowed unless `strict = true`. |
| `1` | At least one `FAIL` or `ERROR`, or a `WARN` in strict mode. |
| `2` | Invalid command-line arguments, or a missing or invalid config. |
| `3` | Owlet itself crashed outside a check, for example a check module that fails to import or a `validate` function that raises something other than `ConfigError`. Owlet prints the traceback to stderr. This is a bug in owlet or a check, not a problem with the site. A crash inside a running check is reported as that check's `ERROR` result instead, and the other checks still run. |
| `130` | The run was interrupted with Ctrl+C. |

### JSON output

`--json` prints one JSON document to stdout. Exit codes are the same as for the table. Config and argument errors still print as text to stderr, with exit code 2, and internal errors print a traceback to stderr, with exit code 3.

```json
{
  "owlet_version": "0.1.0",
  "target": "https://example.com",
  "strict": false,
  "started_at": "2026-10-18T09:30:00+00:00",
  "duration_seconds": 0.734,
  "exit_code": 1,
  "summary": { "PASS": 1, "WARN": 0, "FAIL": 1, "SKIP": 0, "ERROR": 0 },
  "results": [
    {
      "check": "http_status", "name": null, "status": "PASS", "summary": "Got status code 200.",
      "details": [], "data": {}, "duration_seconds": 0.412, "fails_run": false, "traceback": null
    },
    {
      "check": "broken_links", "name": null, "status": "FAIL", "summary": "2 of 31 links broken:",
      "details": ["https://example.com/old (404)", "https://cdn.example.com/x.js (ConnectError)"],
      "data": {}, "duration_seconds": 0.731, "fails_run": true, "traceback": null
    }
  ]
}
```

- `started_at` is in UTC. `duration_seconds` at the top is the whole run. On a result, it's how long that check took, and every result from one check shares it.
- `details` holds extra lines for people, such as each broken link. `data` holds values for scripts, and its keys depend on the check.
- `summary` always has all five statuses, including those with a count of 0. It counts every result, even with `--quiet`.
- `name` is `null` unless the check produces several results, like `security_headers` does per header.
- `traceback` is the Python traceback when the check crashed with an `ERROR`, and `null` otherwise.
- `fails_run` says whether that result makes the run fail, with strict mode already applied. To get only the failures, use `--quiet`, which leaves only results with `fails_run: true`.

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
- **Results:** return one `Result`, return an iterable of them, or `yield` them from an async generator. Use `name=` to tell several results from one check apart, as `security_headers` does for each header. Every `Result` needs a status and a `summary`: one non-empty line saying what the check found. A summary with a line break becomes an `ERROR`, so put extra lines for people in `details=` (a list of strings, printed indented under the summary), as `broken_links` does for each broken link. Put values for scripts in `data=` (a JSON-serializable dict, only shown in `--json` output), such as `data={"days_left": 69}`. Owlet fills in `check_name` and `duration_seconds` itself.
- **Errors:** you don't need to catch network errors; they become `FAIL` automatically. Any other exception becomes `ERROR`.
- **Option values:** owlet checks option types for you. To reject values of the right type that the check can't use, pass a `validate` function to `@check`. It takes every option as a keyword argument and raises `ConfigError` (from `owlet.config`) for a bad value. Owlet calls it for every available check when the config loads, even checks that aren't in `active_checks` or have no `[checks.<name>]` table (then with the defaults), so a bad value stops the run with `Config error:` and exit code 2, before any request is sent. The check itself can then assume its options are valid.

  ```python
  def _validate_has_title(*, min_length: int) -> None:
      if min_length < 1:
          raise ConfigError(f"min_length must be at least 1, got {min_length}.")


  @check(validate=_validate_has_title)
  async def has_title(ctx: Context, *, min_length: int = 1) -> Result:
      ...
  ```
- **Docstring:** shown by `owlet --list-checks`, so write it as a one-line summary of what passing means.

Checks must be `async def` functions, either returning their results or `yield`ing them as an async generator. A plain `def` is rejected when owlet loads the checks.

### Plugins

To keep your checks out of owlet's source, write them the same way in your own files and list them in the config:

```toml
plugins = ["my_checks.py", "checks/"]
active_checks = ["http_status", "has_title"]
```

Each entry is a `.py` file or a folder, relative to the config file. For a folder, owlet imports every `.py` file in it except those starting with `_`. Plugin files run as Python code when the config loads, so only list files you trust. Two plugin files can't share a file name. Plugin files are imported on their own, not as part of a package, so import from other plugin files by adding their folder to `sys.path` or by turning them into a package.

To share checks as an installed package instead, register the module that holds them in the `owlet.checks` entry point group. Owlet imports it on every run, and its checks show in `--list-checks` and `--init` without any `plugins` entry:

```toml
# pyproject.toml of your package
[project.entry-points."owlet.checks"]
my_checks = "my_package.checks"
```

Check names are global: a plugin check with the same name as another check stops owlet with exit code `3`.
