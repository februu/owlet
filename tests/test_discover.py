"""discover_checks: finding built-in checks, plugin files and installed plugin packages."""

import sys
from types import SimpleNamespace

import pytest

from owlet.check import Result, Status, check
from owlet.config import ConfigError
from owlet.discover import ENTRY_POINT_GROUP, PLUGIN_PACKAGE, discover_checks

PLUGIN = """
from owlet.check import Result, Status, check

@check
async def {name}(ctx):
    return Result(Status.PASS, "Fine.")
"""


@pytest.fixture
def write_plugin(tmp_path):
    """Write a plugin file defining one check, named after the file unless told otherwise."""

    def write(file_name: str, check_name: str | None = None, source: str | None = None):
        path = tmp_path / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source or PLUGIN.format(name=check_name or path.stem), encoding="utf-8")
        return path

    return write


def test_built_in_checks_are_found_without_plugins():
    assert "http_status" in discover_checks()


def test_discovery_survives_being_repeated_across_tests():
    """Guards the session fixture in conftest: built-ins must be back in the registry after isolated_registry restores it."""
    assert "http_status" in discover_checks()


def test_plugin_checks_come_after_the_built_in_ones(write_plugin):
    assert list(discover_checks([write_plugin("mine.py")]))[-1] == "mine"


def test_plugin_module_is_named_under_the_plugin_package(write_plugin):
    checks = discover_checks([write_plugin("mine.py")])
    assert checks["mine"].func.__module__ == f"{PLUGIN_PACKAGE}.mine"


def test_importing_the_same_plugin_twice_registers_it_once(write_plugin):
    path = write_plugin("mine.py")
    discover_checks([path])
    assert "mine" in discover_checks([path])


def test_two_plugin_files_with_one_name_are_a_config_error(write_plugin):
    first = write_plugin("a/same.py", "first")
    second = write_plugin("b/same.py", "second")
    with pytest.raises(ConfigError, match="have the same name; rename one"):
        discover_checks([first, second])


@pytest.mark.parametrize(
    ("source", "error"),
    [("def broken(:\n", SyntaxError), ("raise RuntimeError('boom')\n", RuntimeError), ("import owlet_no_such_module\n", ImportError)],
    ids=["syntax-error", "raises", "bad-import"],
)
def test_plugin_that_fails_to_import_is_not_a_config_error_and_is_forgotten(write_plugin, source, error):
    with pytest.raises(error):
        discover_checks([write_plugin("broken.py", source=source)])

    assert f"{PLUGIN_PACKAGE}.broken" not in sys.modules


def test_plugin_check_with_a_taken_name_is_rejected(write_plugin):
    with pytest.raises(ValueError, match="Duplicate check name 'http_status'") as error:
        discover_checks([write_plugin("clash.py", "http_status")])

    assert not isinstance(error.value, ConfigError)


def test_installed_entry_points_are_loaded_from_the_owlet_group(monkeypatch):
    groups = []

    def load():
        @check
        async def from_package(ctx):
            return Result(Status.PASS, "Fine.")

    def entry_points(*, group):
        groups.append(group)
        return [SimpleNamespace(name="pkg", value="pkg.checks", load=load)]

    monkeypatch.setattr("owlet.discover.entry_points", entry_points)

    assert "from_package" in discover_checks()
    assert groups == [ENTRY_POINT_GROUP]


def test_entry_point_that_fails_to_import_names_the_plugin(monkeypatch):
    def load():
        raise ImportError("no module")

    monkeypatch.setattr("owlet.discover.entry_points", lambda *, group: [SimpleNamespace(name="pkg", value="pkg.checks", load=load)])

    with pytest.raises(RuntimeError, match=r"Plugin 'pkg' \(pkg\.checks\) failed to import: no module"):
        discover_checks()
