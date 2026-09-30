"""A config.json carrying a UTF-8 BOM must not disable the plugin.

``plugins/*/config.json`` is a user-edited file: godcmd's is created on first
run for the operator to fill in, and Windows Notepad / PowerShell write UTF-8
with a BOM by default. Plain ``utf-8`` makes ``json.load`` raise
"Unexpected UTF-8 BOM", the plugin's ``__init__`` fails, and
``PluginManager.activate_plugins`` answers a failed init by disabling the
plugin and *persisting* ``enabled=false`` -- so it stayed off across restarts
even after the user put the file right.

``agent/admin.py`` already reads user-edited JSON with ``utf-8-sig`` for
exactly this reason ("utf-8-sig tolerates a UTF-8 BOM (e.g. config.json
edited with Windows Notepad / PowerShell)"). The same convention applied here
to ``Plugin.load_config()`` and to the keyword plugin's inline read.

The tests point each plugin at a config under ``tmp_path`` rather than the
one in the repo: ``__file__`` is what the plugin uses for its own directory,
and ``Plugin.path`` is what ``load_config`` uses, so both are redirected.
"""
import importlib
import json

import pytest

import config
import plugins


@pytest.fixture
def _isolate_global_plugin_config():
    """``Plugin.load_config`` caches into ``config.plugin_config``.

    A leftover entry from another test would be returned instead of the file
    the test just wrote, short-circuiting the case under test.
    """
    for name in ("banwords", "godcmd", "keyword"):
        config.plugin_config.pop(name, None)
    yield
    for name in ("banwords", "godcmd", "keyword"):
        config.plugin_config.pop(name, None)


def _load(module_name, plugin_dir, registry_name):
    """Import the plugin module and return it with its registered class.

    ``plugins.register`` binds the decorated name to ``None`` (its wrapper
    returns nothing), so the class has to be read out of the manager.
    """
    plugins.instance.current_plugin_path = plugin_dir
    try:
        module = importlib.import_module(module_name)
    finally:
        plugins.instance.current_plugin_path = None
    return module, plugins.instance.plugins[registry_name]


def _bom_config(tmp_path, payload):
    """Write a config.json the way Windows Notepad / PowerShell do: BOM first."""
    path = tmp_path / "config.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8"))
    return path


def _point_at(monkeypatch, module, plugin_cls, tmp_path):
    monkeypatch.setattr(module, "__file__", str(tmp_path / f"{module.__name__}.py"))
    monkeypatch.setattr(plugin_cls, "path", str(tmp_path))
    return _bom_config(tmp_path, {})


def test_banwords_starts_with_a_bom_config(tmp_path, monkeypatch, _isolate_global_plugin_config):
    module, banwords = _load("plugins.banwords.banwords", "./plugins/banwords", "BANWORDS")
    monkeypatch.setattr(module, "__file__", str(tmp_path / "banwords.py"))
    monkeypatch.setattr(banwords, "path", str(tmp_path))
    _bom_config(tmp_path, {"action": "replace"})

    plugin = banwords()  # must not raise

    assert plugin.action == "replace"


def test_godcmd_starts_with_a_bom_config(tmp_path, monkeypatch, _isolate_global_plugin_config):
    module, godcmd = _load("plugins.godcmd.godcmd", "./plugins/godcmd", "GODCMD")
    monkeypatch.setattr(module, "__file__", str(tmp_path / "godcmd.py"))
    monkeypatch.setattr(godcmd, "path", str(tmp_path))
    _bom_config(tmp_path, {"password": "set-by-the-user", "admin_users": ["x"]})

    plugin = godcmd()  # must not raise

    assert plugin.password == "set-by-the-user"
    assert plugin.admin_users == ["x"]


def test_keyword_starts_with_a_bom_config(tmp_path, monkeypatch, _isolate_global_plugin_config):
    module, keyword = _load("plugins.keyword.keyword", "./plugins/keyword", "KEYWORD")
    monkeypatch.setattr(module, "__file__", str(tmp_path / "keyword.py"))
    _bom_config(tmp_path, {"keyword": {"hi": "Hello!"}})

    plugin = keyword()  # must not raise

    assert plugin.keyword == {"hi": "Hello!"}
