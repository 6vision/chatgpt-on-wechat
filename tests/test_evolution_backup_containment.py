# encoding:utf-8
"""An undo snapshot must not restore files outside the workspace.

``restore_backup`` reads the destination of every file out of an on-disk
``manifest.json`` and joins it onto the workspace without checking where it
landed. That manifest lives *inside* the workspace, under
``memory/.evolution_backups/<id>/``, so anything that can write there -- an
evolution agent, a skill the agent installed, or an upload that landed in the
workspace -- chooses where undo writes. An entry of ``{"bak": "0.bak",
"rel": "../../.cow/.env"}`` then makes ``shutil.copy2`` overwrite a file outside
the workspace: the API-key file the rest of the toolchain deliberately refuses
to touch, and the user notices it only when a later request 500s.

This is about the destination only. Whether the snapshot is *complete* -- every
payload present, every entry well formed -- is checked separately, before any
file is applied.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.evolution.backup import _BACKUP_DIRNAME, _MANIFEST_NAME, restore_backup


class BackupRestoreContainmentTest(unittest.TestCase):
    """A manifest entry pointing outside the workspace must be refused."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

        self.ws = os.path.join(self.root, "workspace")
        os.makedirs(self.ws)

        # A real workspace file, to prove the fix did not disable undo.
        self.memory = os.path.join(self.ws, "MEMORY.md")
        with open(self.memory, "w", encoding="utf-8") as handle:
            handle.write("current memory")

        # Standing in for the files undo must never reach.
        self.outside_dir = os.path.join(self.root, ".cow")
        os.makedirs(self.outside_dir)
        self.env_file = os.path.join(self.outside_dir, ".env")
        with open(self.env_file, "w", encoding="utf-8") as handle:
            handle.write("API_KEY=secret")

        self.outside_file = os.path.join(self.root, "other.txt")
        with open(self.outside_file, "w", encoding="utf-8") as handle:
            handle.write("untouched")

    def _snapshot(self, entries, payloads):
        """Write a hand-crafted snapshot directory and return its backup id."""
        backup_id = "20260101-000000-000"
        target = os.path.join(
            self.ws, "memory", _BACKUP_DIRNAME, backup_id
        )
        os.makedirs(target)
        for name, body in payloads.items():
            with open(os.path.join(target, name), "w", encoding="utf-8") as handle:
                handle.write(body)
        with open(
            os.path.join(target, _MANIFEST_NAME), "w", encoding="utf-8"
        ) as handle:
            json.dump(entries, handle)
        return backup_id

    def _read(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    # -- the escape ------------------------------------------------------

    def test_a_relative_escape_does_not_overwrite_a_file_outside(self):
        """'../' in ``rel`` used to be followed straight out of the workspace."""
        backup_id = self._snapshot(
            [{"bak": "0.bak", "rel": "../.cow/.env"}],
            {"0.bak": "API_KEY=stolen"},
        )

        self.assertFalse(restore_backup(self.ws, backup_id))
        self.assertEqual(
            self._read(self.env_file),
            "API_KEY=secret",
            "undo wrote outside the workspace from a traversal manifest entry",
        )

    def test_a_deeper_escape_does_not_overwrite_a_file_outside(self):
        """A longer ``..`` chain is refused the same way."""
        backup_id = self._snapshot(
            [{"bak": "0.bak", "rel": "../../other.txt"}],
            {"0.bak": "clobbered"},
        )

        self.assertFalse(restore_backup(self.ws, backup_id))
        self.assertEqual(self._read(self.outside_file), "untouched")

    def test_an_absolute_destination_is_refused(self):
        """``rel`` is joined onto the workspace, and a rooted path wins."""
        backup_id = self._snapshot(
            [{"bak": "0.bak", "rel": self.outside_file}],
            {"0.bak": "clobbered"},
        )

        self.assertFalse(restore_backup(self.ws, backup_id))
        self.assertEqual(self._read(self.outside_file), "untouched")

    def test_an_escape_does_not_take_a_valid_entry_with_it(self):
        """Validation happens before anything is applied, like completeness."""
        memory_backup = os.path.join(self.ws, "MEMORY.md.bak")
        with open(memory_backup, "w", encoding="utf-8") as handle:
            handle.write("original memory")
        backup_id = self._snapshot(
            [
                {"bak": "0.bak", "rel": "MEMORY.md"},
                {"bak": "1.bak", "rel": "../.cow/.env"},
            ],
            {"0.bak": "original memory", "1.bak": "API_KEY=stolen"},
        )
        with open(self.memory, "w", encoding="utf-8") as handle:
            handle.write("edited memory")

        self.assertFalse(restore_backup(self.ws, backup_id))
        self.assertEqual(self._read(self.memory), "edited memory")
        self.assertEqual(self._read(self.env_file), "API_KEY=secret")

    # -- the control: real restores keep working --------------------------

    def test_a_path_inside_the_workspace_is_still_restored(self):
        backup_id = self._snapshot(
            [{"bak": "0.bak", "rel": "MEMORY.md"}],
            {"0.bak": "original memory"},
        )
        with open(self.memory, "w", encoding="utf-8") as handle:
            handle.write("edited memory")

        self.assertTrue(restore_backup(self.ws, backup_id))
        self.assertEqual(self._read(self.memory), "original memory")

    def test_a_nested_path_inside_the_workspace_is_still_restored(self):
        """Undo of a skill file is a nested rel, not a bare name."""
        backup_id = self._snapshot(
            [{"bak": "0.bak", "rel": os.path.join("skills", "custom", "SKILL.md")}],
            {"0.bak": "original skill"},
        )

        self.assertTrue(restore_backup(self.ws, backup_id))
        restored = os.path.join(self.ws, "skills", "custom", "SKILL.md")
        self.assertEqual(self._read(restored), "original skill")

    def test_a_dotdot_that_resolves_back_inside_is_still_restored(self):
        """'skills/../MEMORY.md' normalises back into the workspace."""
        backup_id = self._snapshot(
            [{"bak": "0.bak", "rel": os.path.join("skills", "..", "MEMORY.md")}],
            {"0.bak": "original memory"},
        )
        with open(self.memory, "w", encoding="utf-8") as handle:
            handle.write("edited memory")

        self.assertTrue(restore_backup(self.ws, backup_id))
        self.assertEqual(self._read(self.memory), "original memory")


if __name__ == "__main__":
    unittest.main()
