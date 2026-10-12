"""Reloading a plugin keeps the configuration it already has."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from plugins.plugin_manager import PluginManager


class ReloadPluginKeepsConfigTest(unittest.TestCase):
    """A reload re-instantiates the plugin; it must not reconfigure it."""

    def setUp(self):
        # PluginManager is a singleton; everything touched here is restored.
        self.manager = PluginManager()
        self._saved = {
            attr: getattr(self.manager, attr)
            for attr in ("plugins", "instances", "listening_plugins",
                         "current_plugin_path", "save_config", "disable_plugin")
        }
        self._saved_plugin_config = config.plugin_config
        self.addCleanup(self._restore)

        # @register needs a plugin path before the module is imported.
        self.manager.current_plugin_path = os.path.join(
            tempfile.mkdtemp(prefix="reloadp-"), "godcmd")
        os.makedirs(self.manager.current_plugin_path, exist_ok=True)
        self.manager.save_config = lambda: None
        self.manager.disable_plugin = lambda name: None

        import plugins.godcmd.godcmd as godcmd_mod

        self.godcmd_mod = godcmd_mod
        self._saved_global_config = dict(godcmd_mod.global_config)

        self.godcmd_cls = self.manager.plugins["GODCMD"]
        self.manager.plugins = {"GODCMD": self.godcmd_cls}

    def _restore(self):
        for attr, value in self._saved.items():
            setattr(self.manager, attr, value)
        config.plugin_config = self._saved_plugin_config
        self.godcmd_mod.global_config.clear()
        self.godcmd_mod.global_config.update(self._saved_global_config)
        # Godcmd writes a config.json into its bundle when one is missing.
        path = os.path.join(os.path.dirname(self.godcmd_mod.__file__), "config.json")
        if os.path.exists(path):
            os.remove(path)

    def _configure(self, password="s3cret", admins=("alice",)):
        config.plugin_config = {
            "godcmd": {"password": password, "admin_users": list(admins)}
        }
        self.manager.activate_plugins()
        return self.manager.instances["GODCMD"]

    def test_a_reload_keeps_the_configured_password_and_admins(self):
        before = self._configure()
        self.assertEqual(before.password, "s3cret")
        self.assertEqual(before.admin_users, ["alice"])

        self.assertTrue(self.manager.reload_plugin("GODCMD"))

        after = self.manager.instances["GODCMD"]
        self.assertIsNot(before, after)
        self.assertEqual(after.password, "s3cret")
        self.assertEqual(after.admin_users, ["alice"])
        self.assertIsNone(after.temp_password)

    def test_reloading_a_name_that_is_not_loaded_changes_nothing(self):
        config.plugin_config = {
            "godcmd": {"password": "s3cret", "admin_users": ["alice"]},
            "banwords": {"password": "other", "admin_users": ["bob"]},
        }

        self.assertNotIn("BANWORDS", self.manager.instances)
        self.assertFalse(self.manager.reload_plugin("Banwords"))

        self.assertEqual(
            config.pconf("Banwords"), {"password": "other", "admin_users": ["bob"]},
            "a reload that found nothing to do still erased the config",
        )


if __name__ == "__main__":
    unittest.main()