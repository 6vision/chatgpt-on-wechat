"""What `scan_plugins` reports as new.

The scan reloads every plugin it has already imported, which re-runs each
plugin's `@PluginManager().register(...)` decorator and therefore hands the
manager a brand new class object every time. It then works out which plugins
are new by taking a set difference between the classes it snapshotted before
the loop and the classes in the registry after it -- an identity comparison,
which the reload guarantees will differ.

So a second scan with nothing installed between the two reported every
plugin as brand new, and `#scanp` (plugins/godcmd/godcmd.py:389) prints that
list as "发现新插件". An admin asking "what did I just install?" gets an
answer naming everything in the plugins directory.

The reload is what causes the class swap, so these tests exercise a real one
rather than asserting the consequence directly. Two throwaway plugins stand in
for the shipped ones: the directory the scan walks is pointed at a temp tree
holding just those two, while the packages themselves live under plugins/ --
which is where the `plugins.<name>` import path resolves from. Nothing
bundled is imported, reloaded or left behind.
"""

import importlib
import os
import shutil
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.plugin_manager import PluginManager

_ALPHA = "_scanp_alpha"
_BETA = "_scanp_beta"
_GAMMA = "_scanp_gamma"

_PLUGIN_SRC = """
    from plugins.plugin_manager import PluginManager

    @PluginManager().register(name="{name}", version="0.1")
    class _{cls}:
        def __init__(self):
            # load_plugins() instantiates every enabled plugin, and
            # activate_plugins() reads `.handlers` off the instance.
            self.handlers = []

        def get_handlers(self):
            return []
"""

# Keys the bundled plugins register under. The baseline has to hold them, or
# restoring an empty registry would break every test that runs after these.
_BUNDLED = ("BANWORDS", "COW_CLI", "DUNGEON", "FINISH", "GODCMD", "HELLO",
            "KEYWORD", "LINKAI", "ROLE")


def _package_dir():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo, "plugins")


def _make_plugin(module_name, plugin_name):
    """Write a minimal plugin package where the import path can find it."""
    path = os.path.join(_package_dir(), module_name)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "__init__.py"), "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(
            _PLUGIN_SRC.format(name=plugin_name, cls=module_name.strip("_"))))
    return path


def _register_bundled(pm):
    """Import every bundled plugin so the registry matches a real session.

    Deliberately not `load_plugins()`: that reaches the plugins through
    `_plugins_resource_dir()`, which these tests redirect at the stand-ins, so
    calling it here would register the stand-ins instead of the shipped
    plugins and the baseline would come out empty. Importing the modules
    directly needs no directory at all.

    The stand-ins are skipped by name. They live in the same package, so a
    plain directory listing would sweep them in -- and a baseline holding them
    would make the first scan find nothing, which is the opposite of the
    situation under test.

    Already-imported modules are evicted first. `import_module` returns the
    cached module without re-running it, and the `@register` decorator is what
    puts a plugin in the registry -- so a second call would register nothing
    and the baseline would silently come back empty.

    The registry is replaced rather than emptied: `plugins` is a SortedDict
    whose heap is maintained by `__delitem__`, which `dict.clear()` does not
    go through, so clearing it in place leaves the two out of step and the
    keys come back doubled.
    """
    package_dir = _package_dir()
    from common.sorted_dict import SortedDict

    stand_ins = {_ALPHA, _BETA, _GAMMA}
    pm.plugins = SortedDict(lambda k, v: v.priority, reverse=True)
    for name in sorted(os.listdir(package_dir)):
        if name in stand_ins:
            continue
        if not os.path.isfile(os.path.join(package_dir, name, "__init__.py")):
            continue
        for cached in [m for m in sys.modules
                       if m == f"plugins.{name}" or m.startswith(f"plugins.{name}.")]:
            del sys.modules[cached]
        pm.current_plugin_path = os.path.join(package_dir, name)
        importlib.import_module(f"plugins.{name}")
    pm.current_plugin_path = None


@pytest.fixture
def scanned(tmp_path):
    """Two stand-in plugins on disk, plus the directory listing for them.

    `scan_plugins` derives each plugin's import path from its directory name
    but resolves that path through the real `plugins` package, so the two
    live apart: the package directories are real (importable), while the
    scanned directory only has to be a tree of same-named folders carrying an
    `__init__.py` for `os.path.isfile` to find.
    """
    _make_plugin(_ALPHA, "alpha")
    _make_plugin(_BETA, "beta")

    listing = tmp_path / "scanroot"
    listing.mkdir()
    for module_name in (_ALPHA, _BETA):
        target = listing / module_name
        target.mkdir()
        (target / "__init__.py").write_text("", encoding="utf-8")

    try:
        yield str(listing)
    finally:
        for module_name in (_ALPHA, _BETA, _GAMMA):
            shutil.rmtree(os.path.join(_package_dir(), module_name),
                          ignore_errors=True)
            sys.modules.pop(f"plugins.{module_name}", None)


@pytest.fixture
def manager(scanned, monkeypatch):
    """A PluginManager holding both stand-ins, with the real one put back.

    PluginManager is a process-wide singleton, so the scan's writes to it are
    undone on the way out. Two details make the teardown matter:

    - the snapshot lives in a fresh container, because the scan replaces
      entries in place and a snapshot sharing one would record the "after"
      state;
    - keys the scan added are dropped again afterwards, so a plugin these
      tests installed does not outlive them.

    And one detail makes the baseline matter: it has to hold the bundled
    plugins, or restoring it empties the registry for every test that runs
    later in the same process -- which is exactly what an earlier version of
    this fixture did, and it showed up as `KeyError: 'COW_CLI'` a long way
    from here.
    """
    pm = PluginManager()
    _register_bundled(pm)
    missing = set(_BUNDLED) - set(pm.plugins)
    assert not missing, (
        f"the bundled plugins failed to register ({sorted(missing)}); a "
        "baseline without them would empty the registry on teardown")

    from common.sorted_dict import SortedDict

    attrs = ("plugins", "loaded", "pconf", "instances", "listening_plugins",
             "current_plugin_path", "save_config", "disable_plugin")
    saved = {attr: getattr(pm, attr) for attr in attrs}
    saved_registry = SortedDict(pm.plugins.sort_func,
                                reverse=pm.plugins.reverse)
    saved_registry.update(pm.plugins)

    # Baseline captured; only now may the scan be pointed elsewhere.
    import plugins.plugin_manager as pm_mod
    monkeypatch.setattr(pm_mod, "_plugins_resource_dir", lambda: scanned)

    pm.plugins = SortedDict(lambda k, v: v.priority, reverse=True)
    pm.loaded = {}
    pm.instances = {}
    pm.listening_plugins = {}
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
            if attr == "plugins":
                continue
            setattr(pm, attr, value)
        for name in list(pm.plugins):
            if name not in saved_registry:
                del pm.plugins[name]


def _names(found):
    return sorted(p.name for p in found)


def test_the_first_scan_discovers_the_plugins_on_disk(manager):
    """The scan is how a dropped-in plugin is found, so the first one has to
    report it -- otherwise the tests below would also pass on a scan that
    never finds anything."""
    found = manager.scan_plugins()

    assert _names(found) == ["alpha", "beta"]


def test_a_second_scan_reports_nothing_new(manager):
    """The point of the change: nothing was installed between these two."""
    manager.scan_plugins()

    second = manager.scan_plugins()

    assert _names(second) == [], (
        "a scan with nothing new installed reported "
        f"{_names(second)} as new")


def test_repeated_scans_keep_reporting_nothing_new(manager):
    """Two scans in a row could agree by luck; a fourth has to agree too."""
    for _ in range(3):
        manager.scan_plugins()

    assert _names(manager.scan_plugins()) == []


def test_the_scan_really_is_replacing_the_plugin_classes(manager):
    """Pins the cause, so the tests above cannot start passing by the reload
    quietly ceasing: with stable classes the identity comparison would be
    harmless and this fix would go untested."""
    manager.scan_plugins()
    before = dict(manager.plugins)

    manager.scan_plugins()

    replaced = [n for n, cls in manager.plugins.items()
                if n in before and before[n] is not cls]
    assert replaced, "scan_plugins no longer recreates plugin classes"


def test_a_plugin_installed_between_two_scans_is_still_reported(manager, scanned):
    """Keying on the registry key must not also swallow real additions.

    Dropped in on disk rather than poked into the registry: a directory
    appearing is the only thing a real installation does, and poking the
    registry would make the scan's own snapshot treat it as pre-existing.
    """
    manager.scan_plugins()

    _make_plugin(_GAMMA, "gamma")
    gamma_listing = os.path.join(scanned, _GAMMA)
    os.makedirs(gamma_listing, exist_ok=True)
    with open(os.path.join(gamma_listing, "__init__.py"), "w",
              encoding="utf-8") as fh:
        fh.write("")

    found = manager.scan_plugins()

    assert "gamma" in _names(found), (
        "a newly installed plugin went unreported; scan said "
        f"{_names(found)}")
