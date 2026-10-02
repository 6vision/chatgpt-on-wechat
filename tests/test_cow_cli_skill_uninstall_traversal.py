# encoding:utf-8
"""``/skill uninstall`` must not delete anything outside the skills directory.

The chat command reads the skill name straight out of the message and joins it
onto the skills directory, then hands whatever that resolves to
``shutil.rmtree``. A name of ``../victim`` therefore resolves to a directory
sitting beside the skills directory, the existence check is satisfied, and the
recursive delete takes the whole tree with it -- the user's other skills, or
anything else a ``..`` chain can reach, including the agent's own state under
``~/.cow``.

The ``cow skill uninstall`` CLI already refuses such names: it runs the name
through ``_check_skill_name``, whose pattern allows only letters, digits,
hyphens and underscores. The chat path never called that check, so the same
command was safe from a terminal and destructive from a chat message -- and a
chat message can arrive from a group, a scheduled task, or a skill that was
handed the uninstall verb.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import plugins

_old_plugin_path = plugins.instance.current_plugin_path
plugins.instance.current_plugin_path = os.path.join(
    os.getcwd(), "plugins", "cow_cli"
)
try:
    from plugins.cow_cli.cow_cli import KNOWN_COMMANDS  # noqa: F401
finally:
    plugins.instance.current_plugin_path = _old_plugin_path

CowCliPlugin = plugins.instance.plugins["COW_CLI"]


class SkillUninstallTraversalTest(unittest.TestCase):
    """A traversal name in a chat message must be rejected, not executed."""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

        # A skills directory with one legitimate skill, and a directory beside
        # it standing in for anything else the user keeps nearby.
        self.skills_dir = os.path.join(self.root, "skills")
        self.keep_skill = os.path.join(self.skills_dir, "alpha")
        os.makedirs(self.keep_skill)
        with open(
            os.path.join(self.keep_skill, "SKILL.md"), "w", encoding="utf-8"
        ) as handle:
            handle.write("# alpha\n")

        self.victim = os.path.join(self.root, "victim")
        os.makedirs(self.victim)
        self.victim_file = os.path.join(self.victim, "important.txt")
        with open(self.victim_file, "w", encoding="utf-8") as handle:
            handle.write("must survive\n")

        import cli.utils

        self._utils = cli.utils
        self._real_get_skills_dir = cli.utils.get_skills_dir
        cli.utils.get_skills_dir = lambda: self.skills_dir
        self.addCleanup(self._restore)

    def _restore(self):
        self._utils.get_skills_dir = self._real_get_skills_dir

    def test_relative_name_cannot_delete_a_sibling_directory(self):
        """``/skill uninstall ../victim`` must not wipe the sibling tree."""
        CowCliPlugin()._skill_uninstall("../victim")

        self.assertTrue(
            os.path.exists(self.victim_file),
            "chat /skill uninstall deleted a directory outside the skills "
            "directory, because the name was joined onto it unchecked",
        )

    def test_deeper_traversal_cannot_delete_the_parent_tree(self):
        """A longer ``..`` chain must not escape either."""
        CowCliPlugin()._skill_uninstall("..")

        self.assertTrue(
            os.path.exists(self.skills_dir),
            "chat /skill uninstall deleted the skills directory's parent",
        )
        self.assertTrue(os.path.exists(self.victim_file))

    def test_absolute_name_cannot_delete_an_arbitrary_tree(self):
        """An absolute name must not be honoured either."""
        CowCliPlugin()._skill_uninstall(self.victim)

        self.assertTrue(
            os.path.exists(self.victim_file),
            "chat /skill uninstall accepted an absolute path as a skill name",
        )

    def test_a_legitimate_skill_is_still_removed(self):
        """The fix must not turn into "uninstall nothing"."""
        CowCliPlugin()._skill_uninstall("alpha")

        self.assertFalse(os.path.exists(self.keep_skill))
        self.assertTrue(os.path.exists(self.victim_file))


if __name__ == "__main__":
    unittest.main()
