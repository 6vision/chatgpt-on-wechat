"""`scan_plugins` reports only plugins that are new since the last scan, despite reloads swapping classes."""

import importlib
import os
import shutil
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.sorted_dict import SortedDict
from plugins.plugin_manager import PluginManager

_ALPHA, _BETA, _GAMMA = "_scanp_alpha", "_scanp_beta", "_scanp_gamma"
_STAND_INS = (_ALPHA, _BETA, _GAMMA)
_PACKAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins")
# The restored baseline must hold these, or later tests in the process lose them.
_BUNDLED = ("BANWORDS", "COW_CLI", "DUNGEON", "FINISH", "GODCMD", "HELLO", "KEYWORD", "ROLE")

_PLUGIN_SRC = """
    from plugins.plugin_manager import PluginManager

    @PluginManager().register(name="{name}", version="0.1")
    class _{cls}:
        def __init__(self):
            self.handlers = []

        def get_handlers(self):
            return []
"""


def _new_registry():
    # Replace rather than clear(): SortedDict keeps a heap that dict.clear() bypasses.
    return SortedDict(lambda k, v: v.priority, reverse=True)


def _make_plugin(module_name, plugin_name, listing):
    path = os.path.join(_PACKAGE_DIR, module_name)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "__init__.py"), "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(_PLUGIN_SRC.format(name=plugin_name, cls=module_name.strip("_"))))
    (listing / module_name).mkdir()
    (listing / module_name / "__init__.py").write_text("", encoding="utf-8")


def _register_bundled(pm):
    # Evict cached modules so @register re-runs and repopulates the registry.
    pm.plugins = _new_registry()
    for name in sorted(os.listdir(_PACKAGE_DIR)):
        if name in _STAND_INS or not os.path.isfile(os.path.join(_PACKAGE_DIR, name, "__init__.py")):
            continue
        for cached in [m for m in sys.modules if m == f"plugins.{name}" or m.startswith(f"plugins.{name}.")]:
            del sys.modules[cached]
        pm.current_plugin_path = os.path.join(_PACKAGE_DIR, name)
        importlib.import_module(f"plugins.{name}")
    pm.current_plugin_path = None


@pytest.fixture
def listing(tmp_path):
    root = tmp_path / "scanroot"
    root.mkdir()
    _make_plugin(_ALPHA, "alpha", root)
    _make_plugin(_BETA, "beta", root)
    try:
        yield root
    finally:
        for module_name in _STAND_INS:
            shutil.rmtree(os.path.join(_PACKAGE_DIR, module_name), ignore_errors=True)
            sys.modules.pop(f"plugins.{module_name}", None)


@pytest.fixture
def manager(listing, monkeypatch):
    pm = PluginManager()
    _register_bundled(pm)
    assert not set(_BUNDLED) - set(pm.plugins)

    attrs = ("loaded", "pconf", "instances", "listening_plugins",
             "current_plugin_path", "save_config", "disable_plugin")
    saved = {attr: getattr(pm, attr) for attr in attrs}
    saved_registry = SortedDict(pm.plugins.sort_func, reverse=pm.plugins.reverse)
    saved_registry.update(pm.plugins)

    import plugins.plugin_manager as pm_mod
    monkeypatch.setattr(pm_mod, "_plugins_resource_dir", lambda: str(listing))

    pm.plugins = _new_registry()
    pm.loaded, pm.instances, pm.listening_plugins = {}, {}, {}
    pm.pconf = {"plugins": {"alpha": {"enabled": True, "priority": 0},
                            "beta": {"enabled": True, "priority": 0}}}
    pm.current_plugin_path = None
    pm.save_config = lambda: None
    pm.disable_plugin = lambda name: None
    try:
        yield pm
    finally:
        pm.plugins = saved_registry
        for attr, value in saved.items():
            setattr(pm, attr, value)


def _names(found):
    return sorted(p.name for p in found)


def test_rescans_report_nothing_new_although_classes_are_replaced(manager):
    assert _names(manager.scan_plugins()) == ["alpha", "beta"]
    for _ in range(3):
        before = dict(manager.plugins)
        assert _names(manager.scan_plugins()) == []
    # Pins the cause: without the reload swapping classes this test proves nothing.
    assert any(before[n] is not cls for n, cls in manager.plugins.items() if n in before)


def test_plugin_installed_between_scans_is_reported(manager, listing):
    manager.scan_plugins()
    _make_plugin(_GAMMA, "gamma", listing)
    assert "gamma" in _names(manager.scan_plugins())
