"""Hand-edited files saved by Windows editors start with a UTF-8 BOM; every
reader of such a file must still parse it."""

import importlib
import json

import pytest

import config
import plugins

BOM = b"\xef\xbb\xbf"


def _write(path, payload):
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    path.write_bytes(BOM + text.encode("utf-8"))


def test_mcp_json(tmp_path):
    from agent.tools.mcp import service

    _write(tmp_path / "mcp.json", {"mcpServers": {"fs": {"command": "npx", "args": []}}})

    assert [s["name"] for s in service.load_servers(workspace=str(tmp_path))] == ["fs"]


def test_backup_config(tmp_path):
    from cli.commands import backup

    _write(tmp_path / "config.json", {"agent_workspace": "/work"})

    assert backup._read_config(tmp_path) == {"agent_workspace": "/work"}


def test_skills_config(tmp_path, monkeypatch):
    from cli import utils

    _write(tmp_path / "skills_config.json", {"beta": {"enabled": False}})
    monkeypatch.setattr(utils, "get_skills_dir", lambda *a, **k: str(tmp_path))

    assert utils.load_skills_config() == {"beta": {"enabled": False}}


@pytest.fixture
def load_plugin(tmp_path, monkeypatch):
    """Import a plugin with its directory and config pointed at tmp_path."""
    monkeypatch.setattr("plugins.plugin.pconf", lambda name: None)
    saved = dict(config.plugin_config)

    def load(package, registry_name):
        plugins.instance.current_plugin_path = f"./plugins/{package}"
        try:
            module = importlib.import_module(f"plugins.{package}.{package}")
        finally:
            plugins.instance.current_plugin_path = None
        plugin_cls = plugins.instance.plugins[registry_name]
        monkeypatch.setattr(module, "__file__", str(tmp_path / f"{package}.py"))
        monkeypatch.setattr(plugin_cls, "path", str(tmp_path))
        return plugin_cls

    yield load
    config.plugin_config.clear()
    config.plugin_config.update(saved)


def test_banwords_config_and_wordlist(tmp_path, load_plugin):
    banwords = load_plugin("banwords", "BANWORDS")
    _write(tmp_path / "config.json", {"action": "replace"})
    _write(tmp_path / "banwords.txt", "百度\n腾讯\n")

    plugin = banwords()

    assert plugin.action == "replace"
    assert plugin.searchr.FindFirst("帮我查一下 百度 的股价")["Keyword"] == "百度"


def test_keyword_config(tmp_path, load_plugin):
    keyword = load_plugin("keyword", "KEYWORD")
    _write(tmp_path / "config.json", {"keyword": {"hi": "Hello!"}})

    assert keyword().keyword == {"hi": "Hello!"}
