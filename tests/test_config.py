import codecs
from pathlib import Path

import pytest

from owlet.config import DEFAULT_USER_AGENT, Config, ConfigError, HttpConfig, load_config, validate_target

TARGET_LINE = 'target = "https://site.test"\n'


@pytest.fixture
def load(tmp_path):
    """Write text to a config file and load it."""

    def write_and_load(text: str) -> Config:
        path = tmp_path / "config.toml"
        path.write_text(text, encoding="utf-8")
        return load_config(path)

    return write_and_load


# Reading the file


def test_minimal_config_gets_the_defaults(load):
    assert load(TARGET_LINE) == Config(target="https://site.test", active_checks=[])
    assert load(TARGET_LINE).check_timeout_seconds == 30.0
    assert load(TARGET_LINE).http == HttpConfig(5.0, DEFAULT_USER_AGENT, {}, True, 100)


def test_full_config_is_read(load, tmp_path):
    (tmp_path / "plugin.py").touch()

    config = load(
        TARGET_LINE
        + """
        active_checks = ["a", "b"]
        strict = true
        check_timeout_seconds = 10
        plugins = ["plugin.py"]

        [checks.a]
        limit = 3
        timeout_seconds = 2

        [checks.b]
        timeout_seconds = 1.5

        [http]
        timeout_seconds = 9
        user_agent = "custom"
        verify = false
        max_connections = 7
        headers = { X-Token = "secret" }
        """
    )

    assert config.active_checks == ["a", "b"]
    assert config.strict is True
    assert config.check_timeout_seconds == 10.0
    assert config.check_options == {"a": {"limit": 3}, "b": {}}, "timeout_seconds isn't an option"
    assert config.check_timeouts == {"a": 2.0, "b": 1.5}
    assert config.plugins == [tmp_path / "plugin.py"]
    assert config.http == HttpConfig(9.0, "custom", {"X-Token": "secret"}, False, 7)


def test_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="Can't read config file"):
        load_config(tmp_path / "missing.toml")


@pytest.mark.parametrize("bom", [codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE], ids=["le", "be"])
def test_utf16_file_is_a_config_error_with_advice(tmp_path, bom):
    path = tmp_path / "config.toml"
    path.write_bytes(bom + TARGET_LINE.encode("utf-16-le"))
    with pytest.raises(ConfigError, match=r"UTF-16.*Out-File -Encoding utf8"):
        load_config(path)


def test_utf8_bom_is_accepted(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(codecs.BOM_UTF8 + TARGET_LINE.encode())
    assert load_config(path).target == "https://site.test"


def test_invalid_utf8_is_a_config_error(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(TARGET_LINE.encode() + b'name = "\xff"\n')
    with pytest.raises(ConfigError, match="isn't valid UTF-8"):
        load_config(path)


def test_invalid_toml_is_a_config_error(load):
    with pytest.raises(ConfigError, match="Invalid TOML"):
        load("target = ")


def test_path_may_be_a_string(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(TARGET_LINE, encoding="utf-8")
    assert load_config(str(path)).target == "https://site.test"


# Rejecting values. Each case is added after a valid target line, so it fails for this reason alone.


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("targt = 1", r"Unknown config key\(s\): targt \(did you mean target\?\)"),
        ("active_checks = 'a'", "'active_checks' must be a list"),
        ("active_checks = [1]", "'active_checks' must be a list"),
        ("strict = 1", "'strict' must be true or false"),
        ("check_timeout_seconds = 0", "'check_timeout_seconds' must be a number greater than 0"),
        ("check_timeout_seconds = -1", "'check_timeout_seconds' must be a number greater than 0"),
        ("check_timeout_seconds = nan", "'check_timeout_seconds' must be a number greater than 0"),
        ("check_timeout_seconds = true", "'check_timeout_seconds' must be a number greater than 0"),
        ("check_timeout_seconds = '5'", "'check_timeout_seconds' must be a number greater than 0"),
        ("checks = 1", "'checks' must be a table"),
        ("checks.a = 1", r"must be a \[checks\.a\] table"),
        ("[checks.a]\ntimeout_seconds = 0", "'checks.a.timeout_seconds' must be a number greater than 0"),
        ("plugins = 'a.py'", "'plugins' must be a list"),
        ("plugins = [1]", "'plugins' must be a list"),
        ("plugins = ['missing.py']", "Plugin 'missing.py' not found"),
        ("http = 1", r"'http' must be an \[http\] table"),
        ("[http]\ntimeut_seconds = 1", r"Unknown key\(s\) in \[http\]: timeut_seconds \(did you mean timeout_seconds\?\)"),
        ("[http]\nfollow_redirects = true", "each check decides whether to follow redirects"),
        ("[http]\ntimeout_seconds = 0", "'http.timeout_seconds' must be a number greater than 0"),
        ("[http]\nuser_agent = ''", "'http.user_agent' must be a non-empty line"),
        ("[http]\nuser_agent = 1", "'http.user_agent' must be a non-empty line"),
        ('[http]\nuser_agent = "a\\nb"', "'http.user_agent' must be a non-empty line"),
        ("[http]\nverify = 'no'", "'http.verify' must be true or false"),
        ("[http]\nmax_connections = 0", "'http.max_connections' must be a whole number"),
        ("[http]\nmax_connections = 1.5", "'http.max_connections' must be a whole number"),
        ("[http]\nmax_connections = true", "'http.max_connections' must be a whole number"),
        ("[http]\nheaders = 1", "'http.headers' must be a table"),
        ("[http.headers]\n'bad name' = 'x'", "invalid header name 'bad name'"),
        ("[http.headers]\nUser-Agent = 'x'", "with 'http.user_agent' instead"),
        ("[http.headers]\nUSER-AGENT = 'x'", "with 'http.user_agent' instead"),
        ("[http.headers]\nX-Token = 1", "'http.headers.X-Token' must be a string"),
        ('[http.headers]\nX-Token = "a\\nb"', "'http.headers.X-Token' must be one line of printable ASCII"),
        ("[http.headers]\nX-Token = 'café'", "'http.headers.X-Token' must be one line of printable ASCII"),
    ],
)
def test_invalid_value_is_a_config_error(load, text, message):
    with pytest.raises(ConfigError, match=message):
        load(TARGET_LINE + text)


# The target


def test_missing_target_is_a_config_error(load):
    with pytest.raises(ConfigError, match="'target' must be set"):
        load("")


@pytest.mark.parametrize("target", ["https://site.test", "http://site.test:8080/path?q=1", "HTTPS://SITE.TEST"])
def test_valid_targets_are_returned_unchanged(target):
    assert validate_target(target) == target


@pytest.mark.parametrize(
    "target",
    ["", "   ", 5, " https://site.test", "https://site.test\n", "site.test", "ftp://site.test", "https://", "https:///path"],
)
def test_invalid_target_is_a_config_error_naming_the_key(target):
    with pytest.raises(ConfigError, match=r"^--target "):
        validate_target(target, "--target")


@pytest.mark.parametrize(
    "target",
    [
        pytest.param(
            "http://[::1", marks=pytest.mark.xfail(raises=ValueError, reason="urlsplit's plain ValueError escapes validate_target")
        ),
        pytest.param("http://site.test:abc", marks=pytest.mark.xfail(reason="passes urlsplit, but httpx rejects it when it's used")),
    ],
)
def test_target_httpx_cannot_parse_is_a_config_error(target):
    with pytest.raises(ConfigError):
        validate_target(target)


# Environment variables in headers


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Bearer ${TOKEN}", "Bearer s3cret"),
        ("${TOKEN}${TOKEN}", "s3crets3cret"),
        ("$$", "$"),
        ("$${TOKEN}", "${TOKEN}"),
        ("100$", "100$"),
        ("${unclosed", "${unclosed"),
    ],
)
def test_header_values_expand_environment_variables(load, monkeypatch, value, expected):
    monkeypatch.setenv("TOKEN", "s3cret")
    config = load(TARGET_LINE + f"[http.headers]\nX-Token = '{value}'")
    assert config.http.headers == {"X-Token": expected}


def test_unset_environment_variable_is_a_config_error(load, monkeypatch):
    monkeypatch.delenv("OWLET_TEST_UNSET", raising=False)
    with pytest.raises(ConfigError, match="OWLET_TEST_UNSET, which isn't set"):
        load(TARGET_LINE + "[http.headers]\nX-Token = '${OWLET_TEST_UNSET}'")


@pytest.mark.parametrize("name", ["", "1A", "A-B", "A B"])
def test_invalid_environment_variable_name_is_a_config_error(load, name):
    with pytest.raises(ConfigError, match="invalid environment variable name"):
        load(TARGET_LINE + f"[http.headers]\nX-Token = '${{{name}}}'")


def test_environment_variable_with_a_line_break_cannot_inject_a_header(load, monkeypatch):
    monkeypatch.setenv("TOKEN", "a\r\nX-Injected: 1")
    with pytest.raises(ConfigError, match="must be one line of printable ASCII"):
        load(TARGET_LINE + "[http.headers]\nX-Token = '${TOKEN}'")


# Plugin paths


def test_plugin_paths_are_relative_to_the_config_file_not_the_working_directory(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "plugin.py").touch()
    (config_dir / "config.toml").write_text(TARGET_LINE + "plugins = ['plugin.py']", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert load_config(config_dir / "config.toml").plugins == [config_dir / "plugin.py"]


def test_plugin_folder_expands_to_its_public_modules_in_sorted_order(load, tmp_path):
    folder = tmp_path / "checks"
    folder.mkdir()
    for name in ["b.py", "a.py", "_private.py", "__init__.py", "notes.txt"]:
        (folder / name).touch()
    (folder / "nested").mkdir()
    (folder / "nested" / "c.py").touch()

    config = load(TARGET_LINE + "plugins = ['checks/']")

    assert [Path(path).name for path in config.plugins] == ["a.py", "b.py"]


def test_plugin_must_be_a_python_file(load, tmp_path):
    (tmp_path / "notes.txt").touch()
    with pytest.raises(ConfigError, match=r"Plugin 'notes\.txt' must be a \.py file"):
        load(TARGET_LINE + "plugins = ['notes.txt']")
