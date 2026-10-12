"""Re-enabling a plugin must not register the same event listener twice.

``PluginManager.activate_plugins`` appended the plugin name to
``listening_plugins[event]`` unconditionally, and ``enable_plugin`` calls it for
plugins that are already registered (as does godcmd's ``#scanp``). ``emit_event``
then walks that list and calls the handler once per entry, so a single toggle was
enough to make an ``ON_DECORATE_REPLY`` plugin mutate the reply twice -- and since
nothing ever removed the stale entry, every other enabled plugin was dispatched
twice as well. The sibling ``reload_plugin`` already removed the name first, which
is what shows the list is meant to hold one entry per plugin.

The manager is built through ``new_instance()`` (as
``tests/test_plugin_store_atomic_write.py`` does) so the test does not inherit the
process-wide singleton, and the plugin dirs are redirected at tmp_path because
``enable_plugin``/``disable_plugin`` persist the toggled state.
"""
import pytest

from plugins import plugin_manager
from plugins.event import Event, EventContext

PLUGIN = "DUPLICATE"
EVENT = Event.ON_DECORATE_REPLY


class FakePlugin:
    """Stands in for a registered plugin class.

    Every instantiation appends to a class-level log, so the count survives the
    re-instantiation ``activate_plugins`` performs on each activation.
    """

    enabled = True
    priority = 0
    name = PLUGIN
    path = "."
    dispatches = []

    def __init__(self):
        self.handlers = {EVENT: self._handle}

    def _handle(self, e_context, *args, **kwargs):
        type(self).dispatches.append(self)


@pytest.fixture(autouse=True)
def _reset_dispatches():
    FakePlugin.dispatches = []
    yield
    FakePlugin.dispatches = []


@pytest.fixture
def manager(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(plugin_manager, "_plugins_data_dir", lambda: str(data_dir))
    pm = plugin_manager.PluginManager.new_instance()
    pm.pconf = {"plugins": {PLUGIN: {"enabled": True, "priority": 0}}}
    return pm


def _register(pm, name, plugin_cls, priority=0):
    plugin_cls.enabled = True
    plugin_cls.priority = priority
    plugin_cls.name = name
    pm.plugins[name] = plugin_cls


def _reenable(pm, name):
    """The real user path: activate, toggle off, toggle back on."""
    pm.activate_plugins()
    pm.disable_plugin(name)
    assert pm.enable_plugin(name)[0] is True


def test_re_enabling_a_plugin_leaves_one_listener_per_event(manager):
    _register(manager, PLUGIN, FakePlugin)

    _reenable(manager, PLUGIN)

    assert manager.listening_plugins[EVENT] == [PLUGIN]


def test_a_re_enabled_plugin_is_dispatched_once_per_event(manager):
    """The user-visible half: the handler must run exactly once."""
    _register(manager, PLUGIN, FakePlugin)

    _reenable(manager, PLUGIN)
    manager.emit_event(EventContext(EVENT))

    assert len(FakePlugin.dispatches) == 1


def test_toggling_twice_does_not_accumulate_listeners(manager):
    _register(manager, PLUGIN, FakePlugin)

    for _ in range(2):
        _reenable(manager, PLUGIN)

    assert manager.listening_plugins[EVENT] == [PLUGIN]
    manager.emit_event(EventContext(EVENT))
    assert len(FakePlugin.dispatches) == 1


def test_de_dup_does_not_drop_another_plugins_listener(manager):
    """Guards against a fix that clears the whole event list instead."""
    other = type("OtherPlugin", (FakePlugin,), {"dispatches": []})
    _register(manager, PLUGIN, FakePlugin)
    _register(manager, "OTHER", other)

    _reenable(manager, PLUGIN)
    manager.emit_event(EventContext(EVENT))

    listeners = manager.listening_plugins[EVENT]
    assert sorted(listeners) == sorted([PLUGIN, "OTHER"])
    assert len(FakePlugin.dispatches) == 1
    assert len(other.dispatches) == 1


def test_priority_order_is_still_applied_after_a_re_enable(manager):
    """``activate_plugins`` ends with ``refresh_order``; a de-dup must not skip it."""
    other = type("OtherPlugin", (FakePlugin,), {"dispatches": [], "priority": 9})
    _register(manager, PLUGIN, FakePlugin)
    _register(manager, "OTHER", other, priority=9)
    manager.pconf["plugins"]["OTHER"] = {"enabled": True, "priority": 9}

    _reenable(manager, PLUGIN)

    # OTHER outranks PLUGIN, so it must come first in the dispatch list.
    assert manager.listening_plugins[EVENT] == ["OTHER", PLUGIN]
