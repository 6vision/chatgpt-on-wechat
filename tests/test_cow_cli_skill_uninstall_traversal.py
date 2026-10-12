# encoding:utf-8
"""Chat `/skill uninstall` rejects names that would delete outside the skills directory."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cli.utils
import plugins

_old_plugin_path = plugins.instance.current_plugin_path
plugins.instance.current_plugin_path = os.path.join(os.getcwd(), "plugins", "cow_cli")
try:
    from plugins.cow_cli.cow_cli import KNOWN_COMMANDS  # noqa: F401
finally:
    plugins.instance.current_plugin_path = _old_plugin_path

CowCliPlugin = plugins.instance.plugins["COW_CLI"]


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    (skills / "alpha").mkdir(parents=True)
    (tmp_path / "victim").mkdir()
    (tmp_path / "victim" / "important.txt").write_text("keep")
    monkeypatch.setattr(cli.utils, "get_skills_dir", lambda: str(skills))
    return skills, tmp_path / "victim"


@pytest.mark.parametrize("absolute", [False, True])
def test_traversal_name_is_refused(dirs, absolute):
    _, victim = dirs
    CowCliPlugin()._skill_uninstall(str(victim) if absolute else "../victim")
    assert (victim / "important.txt").exists()


def test_valid_skill_is_removed(dirs):
    skills, _ = dirs
    CowCliPlugin()._skill_uninstall("alpha")
    assert not (skills / "alpha").exists()
