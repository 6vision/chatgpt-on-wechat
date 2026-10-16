"""``/skill`` typed in an Agent's chat acts on that Agent's skills.

An Agent with its own ``skills/`` directory does not read the shared library,
so a command that silently wrote to the shared one reported success while the
Agent it was typed to never saw the change.
"""
import json
import os

import plugins

_old_plugin_path = plugins.instance.current_plugin_path
plugins.instance.current_plugin_path = os.path.join(os.getcwd(), "plugins", "cow_cli")
try:
    import plugins.cow_cli.cow_cli  # noqa: F401
finally:
    plugins.instance.current_plugin_path = _old_plugin_path

CowCliPlugin = plugins.instance.plugins["COW_CLI"]


def _two_libraries(tmp_path, monkeypatch):
    """A shared library and one Agent's own, each holding a skill ``alpha``."""
    dirs = {None: tmp_path / "shared", "helper": tmp_path / "helper" / "skills"}
    for d in dirs.values():
        (d / "alpha").mkdir(parents=True)
        (d / "alpha" / "SKILL.md").write_text("# alpha\n", encoding="utf-8")
        (d / "skills_config.json").write_text(
            json.dumps({"alpha": {"name": "alpha", "enabled": True}}), encoding="utf-8")
    monkeypatch.setattr("cli.utils.get_skills_dir", lambda agent_id=None: str(dirs[agent_id]))
    monkeypatch.setattr(CowCliPlugin, "_current_agent_id", lambda self, e_context: "helper")
    return dirs


def _enabled(skills_dir):
    return json.loads((skills_dir / "skills_config.json").read_text(encoding="utf-8"))["alpha"]["enabled"]


def test_install_targets_the_agent_the_command_was_typed_to(monkeypatch):
    calls = []

    def _install(name, agent_id=None):
        from cli.commands.skill import InstallResult
        calls.append((name, agent_id))
        return InstallResult(error="stop here")

    monkeypatch.setattr("cli.commands.skill.install_skill", _install)
    monkeypatch.setattr(CowCliPlugin, "_current_agent_id", lambda self, e_context: "helper")

    CowCliPlugin()._cmd_skill("install pptx", None)

    assert calls == [("pptx", "helper")]


def test_disable_changes_only_the_agents_own_copy(tmp_path, monkeypatch):
    dirs = _two_libraries(tmp_path, monkeypatch)

    CowCliPlugin()._cmd_skill("disable alpha", None)

    assert _enabled(dirs["helper"]) is False
    assert _enabled(dirs[None]) is True


def test_uninstalling_an_own_copy_keeps_the_shared_one_and_its_selections(tmp_path, monkeypatch):
    dirs = _two_libraries(tmp_path, monkeypatch)
    pruned = []

    class _Admin:
        def prune_skill(self, name):
            pruned.append(name)

    monkeypatch.setattr("agent.admin.get_agent_admin_service", lambda: _Admin())

    CowCliPlugin()._cmd_skill("uninstall alpha", None)

    assert not (dirs["helper"] / "alpha").exists()
    assert (dirs[None] / "alpha").exists()
    assert pruned == []
