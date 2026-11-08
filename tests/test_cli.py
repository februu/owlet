"""The command line, end to end: arguments, exit codes and output. No test here touches the network."""

import json
import os
import re
import subprocess
import sys

import pytest

from owlet.check import Result, Status, check, registry
from owlet.cli import main
from owlet.config import load_config
from owlet.discover import discover_checks
from owlet.plan import resolve

TARGET = "https://site.test"

PLUGIN = '''
import sys

from owlet.check import Result, Status, check


@check
async def exits(ctx):
    sys.exit(7)


@check
async def passes(ctx, *, limit: int = 3):
    """Always passes."""
    return Result(Status.PASS, "All good.", data={"limit": limit})


@check
async def warns(ctx):
    return Result(Status.WARN, "Looks odd.")


@check
async def skips(ctx):
    return Result(Status.SKIP, "Doesn't apply.")


@check
async def fails(ctx):
    return Result(Status.FAIL, "Found a problem.", name="part", details=["first detail", "second detail"])


@check
async def crashes(ctx):
    raise ValueError("boom")


@check
async def shows_target(ctx):
    return Result(Status.PASS, ctx.target)


@check
async def markup(ctx):
    return Result(Status.PASS, "[red]not markup[/red]", details=["[bold]neither[/bold]"])


@check
async def long_line(ctx):
    return Result(Status.PASS, "x" * 500, details=["y" * 500])


@check
async def fancy(ctx):
    return Result(Status.PASS, "caf\\u00e9 \\u2192 \\u65e5\\u672c\\u8a9e")
'''


@pytest.fixture(autouse=True)
def no_network(site):
    """Send anything a test's checks request to the fake site."""


@pytest.fixture
def config(tmp_path):
    """Write a config running the given checks from the plugin above, and return its path as a string."""

    def write(*active: str, extra: str = "") -> str:
        (tmp_path / "plugin.py").write_text(PLUGIN, encoding="utf-8")
        path = tmp_path / "config.toml"
        path.write_text(f"target = {json.dumps(TARGET)}\nplugins = ['plugin.py']\nactive_checks = {json.dumps(active)}\n{extra}", "utf-8")
        return str(path)

    return write


def exit_code(*argv: str) -> int:
    """The process's exit code: main's return value, or the code argparse exits with."""
    try:
        return main(list(argv))
    except SystemExit as e:
        return e.code


def run_json(capsys, *argv: str) -> tuple[int, dict]:
    code = exit_code(*argv, "--json")
    return code, json.loads(capsys.readouterr().out)


# Arguments


def test_no_arguments_prints_help(capsys):
    assert exit_code() == 0
    assert "usage: owlet" in capsys.readouterr().out


def test_version(capsys):
    assert exit_code("--version") == 0
    assert re.fullmatch(r"owlet \d+\.\d+\.\d+.*\n", capsys.readouterr().out)


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["init"], "Did you mean --init?"),
        (["list-checks"], "Did you mean --list-checks?"),
        (["--jsn"], "--jsn (did you mean --json?)"),
        (["--jsn=1"], "--jsn=1 (did you mean --json?)"),
        (["a.toml", "b.toml"], "unrecognized arguments: b.toml"),
        (["--init", "site.test"], "--init must be an http:// or https:// URL"),
        (["--target", "ftp://site.test"], "--target must be an http:// or https:// URL"),
        (["--list-checks", "--init", TARGET], "can't be used together"),
        (["a.toml", "--init", TARGET], "--init doesn't take a config file"),
        (["--list-checks", "--target", TARGET], "--list-checks doesn't take --target"),
        (["--init", TARGET, "--target", TARGET], "--init doesn't take --target"),
        (["--only", "passes"], "need a config file or --target"),
        (["--strict"], "need a config file or --target"),
        (["--quiet"], "need a config file or --target"),
        (["--verbose"], "need a config file or --target"),
        (["--json"], "need a config file or --target"),
    ],
)
def test_bad_arguments_exit_2_saying_what_to_do(capsys, argv, message):
    assert exit_code(*argv) == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    "target",
    [
        pytest.param(
            "http://[::1", marks=pytest.mark.xfail(reason="the ValueError from urlsplit escapes validate_target, so this exits 3")
        ),
        pytest.param("http://site.test:abc", marks=pytest.mark.xfail(reason="passes validation, so the run starts anyway")),
    ],
)
def test_target_httpx_cannot_parse_exits_2(config, target):
    assert exit_code(config("passes"), "--target", target) == 2


# Config errors


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("nonsense = 1", "Unknown config key(s): nonsense"),
        ("[checks.passes]\nlimit = 'lots'", "Option 'passes.limit' must be int"),
        ("[checks.passes]\nlimt = 1", "limt (did you mean limit?)"),
        ("[checks.nope]\nx = 1", "Unknown checks: nope"),
    ],
)
def test_invalid_config_exits_2_without_running_anything(capsys, config, site, extra, message):
    assert exit_code(config("passes", extra=extra)) == 2

    captured = capsys.readouterr()
    assert captured.err.startswith("Config error: ")
    assert message in captured.err
    assert captured.out == ""
    assert site.client_kwargs == {}, "no HTTP client should be created"


def test_missing_config_exits_2(capsys, tmp_path):
    assert exit_code(str(tmp_path / "missing.toml")) == 2
    assert "Config error: Can't read config file" in capsys.readouterr().err


def test_unknown_only_exits_2_with_a_suggestion(capsys, config):
    assert exit_code(config("passes"), "--only", "pases") == 2
    assert "Unknown checks: pases (did you mean passes?)" in capsys.readouterr().err


def test_no_active_checks_exits_2(capsys, config):
    assert exit_code(config()) == 2
    assert "No checks to run" in capsys.readouterr().err


# Exit codes


@pytest.mark.parametrize(
    ("active", "flags", "extra", "expected"),
    [
        (["passes"], [], "", 0),
        (["skips"], [], "", 0),
        (["warns"], [], "", 0),
        (["warns"], ["--strict"], "", 1),
        (["warns"], [], "strict = true", 1),
        (["passes"], ["--strict"], "", 0),
        (["skips"], ["--strict"], "", 0),
        (["fails"], [], "", 1),
        (["crashes"], [], "", 1),
        (["passes", "fails"], [], "", 1),
        (["fails"], ["--only", "passes"], "", 0),
    ],
)
def test_exit_code_reflects_the_results(config, active, flags, extra, expected):
    assert exit_code(config(*active, extra=extra), *flags) == expected


@pytest.mark.parametrize(
    "source",
    [
        "def broken(:\n",
        "raise RuntimeError('boom')\n",
        "from owlet.check import check\n@check\nasync def http_status(ctx):\n    pass\n",
        "from owlet.check import check\n@check\ndef not_async(ctx):\n    pass\n",
        "from owlet.check import check\n"
        "def validate(**options):\n    raise KeyError('oops')\n"
        "@check(validate=validate)\nasync def crashes_validating(ctx):\n    pass\n",
    ],
    ids=["syntax-error", "raises", "duplicate-name", "not-async", "validate-crashes"],
)
def test_plugin_crash_exits_3_with_a_traceback(capsys, tmp_path, source):
    (tmp_path / "plugin.py").write_text(source, encoding="utf-8")
    path = tmp_path / "config.toml"
    path.write_text(f"target = {json.dumps(TARGET)}\nplugins = ['plugin.py']\nactive_checks = ['http_status']\n", encoding="utf-8")

    assert exit_code(str(path)) == 3

    err = capsys.readouterr().err
    assert "Traceback" in err
    assert "Internal error" in err
    assert "not a problem with the site" in err


def test_ctrl_c_exits_130(capsys):
    @check
    async def interrupted(ctx):
        raise KeyboardInterrupt

    assert exit_code("--target", TARGET, "--only", "interrupted") == 130
    assert "Interrupted." in capsys.readouterr().err


# Choosing what to run


def test_results_follow_active_checks_order(capsys, config):
    _, document = run_json(capsys, config("warns", "passes"))
    assert [result["check"] for result in document["results"]] == ["warns", "passes"]


def test_only_replaces_active_checks_in_the_order_given(capsys, config):
    _, document = run_json(capsys, config("fails"), "--only", "warns", "--only", "passes", "--only", "warns")
    assert [result["check"] for result in document["results"]] == ["warns", "passes"]


def test_config_options_reach_the_check(capsys, config):
    _, document = run_json(capsys, config("passes", extra="[checks.passes]\nlimit = 9"))
    assert document["results"][0]["data"] == {"limit": 9}


def test_target_flag_overrides_the_config(capsys, config):
    _, document = run_json(capsys, config("shows_target"), "--target", "https://other.test")
    assert document["target"] == "https://other.test"
    assert document["results"][0]["summary"] == "https://other.test"


def test_target_without_config_runs_every_check():
    registry._checks.clear()
    ran = []

    @check
    async def first(ctx):
        ran.append("first")
        return Result(Status.PASS, "Fine.")

    @check
    async def second(ctx):
        ran.append("second")
        return Result(Status.PASS, "Fine.")

    assert exit_code("--target", TARGET) == 0
    assert ran == ["first", "second"]


def test_target_without_config_can_be_narrowed_with_only(capsys):
    @check
    async def wanted(ctx):
        return Result(Status.PASS, "Fine.")

    code, document = run_json(capsys, "--target", TARGET, "--only", "wanted")

    assert code == 0
    assert [result["check"] for result in document["results"]] == ["wanted"]


# JSON output


def test_json_document_has_the_documented_shape(capsys, config):
    code, document = run_json(capsys, config("passes", "fails", "crashes"))

    assert code == 1
    assert document["target"] == TARGET
    assert document["strict"] is False
    assert document["exit_code"] == 1
    assert document["owlet_version"]
    assert document["started_at"].endswith("+00:00")
    assert document["duration_seconds"] >= 0
    assert document["summary"] == {"PASS": 1, "WARN": 0, "FAIL": 1, "SKIP": 0, "ERROR": 1}

    passes, fails, crashes = document["results"]
    assert set(passes) == {"check", "name", "status", "summary", "details", "data", "duration_seconds", "fails_run", "traceback"}
    assert (passes["check"], passes["name"], passes["status"], passes["fails_run"]) == ("passes", None, "PASS", False)
    assert (fails["name"], fails["status"], fails["fails_run"]) == ("part", "FAIL", True)
    assert fails["details"] == ["first detail", "second detail"]
    assert (crashes["status"], crashes["fails_run"]) == ("ERROR", True)
    assert "ValueError: boom" in crashes["traceback"]


def test_json_applies_strict_mode_to_fails_run(capsys, config):
    code, document = run_json(capsys, config("warns"), "--strict")
    assert code == 1
    assert document["strict"] is True
    assert document["results"][0]["fails_run"] is True


def test_quiet_json_lists_only_failures_but_counts_everything(capsys, config):
    _, document = run_json(capsys, config("passes", "fails"), "--quiet")
    assert [result["check"] for result in document["results"]] == ["fails"]
    assert document["summary"]["PASS"] == 1


def test_quiet_json_with_no_failures_still_prints_the_document(capsys, config):
    code, document = run_json(capsys, config("passes"), "--quiet")
    assert code == 0
    assert document["results"] == []
    assert document["summary"]["PASS"] == 1


def test_config_error_with_json_goes_to_stderr_as_text(capsys, config):
    assert exit_code(config("nope"), "--json") == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Config error: ")


# Table output


def test_table_shows_status_label_summary_details_and_counts(capsys, config):
    assert exit_code(config("passes", "warns", "fails")) == 1

    lines = capsys.readouterr().out.splitlines()

    assert re.fullmatch(r"PASS\s+passes\s+All good\.", lines[0])
    assert re.fullmatch(r"WARN\s+warns\s+Looks odd\.", lines[1])
    assert re.fullmatch(r"FAIL\s+fails - part\s+Found a problem\.", lines[2])
    assert lines[3].endswith("  first detail")
    assert lines[4].endswith("  second detail")
    assert lines[5] == ""
    assert re.fullmatch(r"1 pass, 1 warn, 1 fail in \d+\.\d\ds", lines[6])


def test_traceback_is_shown_only_with_verbose(capsys, config):
    path = config("crashes")

    exit_code(path)
    assert "Traceback" not in capsys.readouterr().out

    exit_code(path, "--verbose")
    out = capsys.readouterr().out
    assert "Traceback" in out
    assert "ValueError: boom" in out


def test_quiet_shows_only_failures_but_counts_everything(capsys, config):
    exit_code(config("passes", "fails"), "--quiet")

    out = capsys.readouterr().out

    assert "All good." not in out
    assert "Found a problem." in out
    assert "1 pass, 1 fail" in out


@pytest.mark.parametrize(("active", "flags"), [(["passes"], []), (["warns", "skips"], [])])
def test_quiet_with_no_failures_prints_nothing(capsys, config, active, flags):
    assert exit_code(config(*active), "--quiet", *flags) == 0
    assert capsys.readouterr().out == ""


def test_quiet_counts_warnings_as_failures_in_strict_mode(capsys, config):
    assert exit_code(config("warns"), "--quiet", "--strict") == 1
    assert "Looks odd." in capsys.readouterr().out


def test_text_from_checks_is_not_read_as_rich_markup(capsys, config):
    exit_code(config("markup"))
    out = capsys.readouterr().out
    assert "[red]not markup[/red]" in out
    assert "[bold]neither[/bold]" in out


# --list-checks


def test_list_checks_shows_built_in_checks_by_module(capsys):
    assert exit_code("--list-checks") == 0
    out = capsys.readouterr().out
    assert "== availability ==" in out
    assert "http_status" in out


def test_list_checks_with_a_config_includes_its_plugins_with_options(capsys, config):
    assert exit_code("--list-checks", config("passes")) == 0

    out = capsys.readouterr().out

    assert "== plugin ==" in out
    assert "Always passes." in out
    assert "limit: int = 3" in out


def test_list_checks_with_an_invalid_config_exits_2(capsys, tmp_path):
    assert exit_code("--list-checks", str(tmp_path / "missing.toml")) == 2
    assert "Config error:" in capsys.readouterr().err


# --init


def init_config(capsys, tmp_path, target: str = TARGET):
    assert exit_code("--init", target) == 0
    path = tmp_path / "config.toml"
    path.write_text(capsys.readouterr().out, encoding="utf-8")
    return path


def test_init_output_loads_and_runs_every_check(capsys, tmp_path):
    settings = load_config(init_config(capsys, tmp_path))
    available = discover_checks()

    plan = resolve(settings, available)

    assert plan.target == TARGET
    assert [planned.check.name for planned in plan.checks] == list(available)


def test_init_output_is_still_valid_with_every_commented_setting_turned_on(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("OWLET_TOKEN", "secret")
    path = init_config(capsys, tmp_path)
    path.write_text(re.sub(r"(?m)^# (\[|\w+ = )", r"\1", path.read_text("utf-8")), encoding="utf-8")

    settings = load_config(path)
    resolve(settings, discover_checks())

    assert settings.http.headers == {"Authorization": "Bearer secret"}
    assert settings.check_options


@pytest.mark.parametrize("target", ['https://site.test/?q="quoted"', "https://site.test/back\\slash", "https://bücher.test/"])
def test_init_escapes_the_target(capsys, tmp_path, target):
    assert load_config(init_config(capsys, tmp_path, target)).target == target


# As a real process with piped output, where the console is chosen at import time


def run_process(*argv: str, encoding: str = "utf-8") -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key not in ("FORCE_COLOR", "TTY_COMPATIBLE", "PYTHONUTF8")}
    env["PYTHONIOENCODING"] = encoding
    program = "import sys; from owlet.cli import main; sys.exit(main(sys.argv[1:]))"
    return subprocess.run(
        [sys.executable, "-c", program, *argv], capture_output=True, encoding="utf-8", errors="replace", env=env, timeout=60
    )


@pytest.mark.parametrize(("active", "expected"), [("passes", 0), ("fails", 1)])
def test_process_exit_code(config, active, expected):
    assert run_process(config(active)).returncode == expected


@pytest.mark.xfail(reason="SystemExit escapes Check.run and TaskGroup re-raises it, so the process exits with the check's code")
def test_check_calling_sys_exit_is_an_error_and_the_others_finish(config):
    process = run_process(config("exits", "passes"), "--json")

    assert process.returncode == 1
    results = json.loads(process.stdout)["results"]
    assert [(result["check"], result["status"]) for result in results] == [("exits", "ERROR"), ("passes", "PASS")]


def test_piped_table_does_not_wrap_or_pad_long_lines(config):
    lines = run_process(config("long_line")).stdout.splitlines()

    assert lines[0].endswith("x" * 500)
    assert lines[1].endswith("y" * 500)


def test_piped_json_survives_a_legacy_output_encoding(config):
    process = run_process(config("fancy"), "--json", encoding="cp1252")

    assert process.returncode == 0
    assert json.loads(process.stdout)["results"][0]["summary"] == "café → 日本語"


@pytest.mark.xfail(reason="print() raises UnicodeEncodeError on characters the output encoding lacks, so a finished run exits 3")
def test_piped_table_survives_a_legacy_output_encoding(config):
    """Windows pipes and redirects default to cp1252 or similar, and summaries can hold any text from the site."""
    process = run_process(config("fancy"), encoding="cp1252")

    assert process.returncode == 0, process.stderr
