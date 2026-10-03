# encoding:utf-8
"""A settings save rejected over one bad value must change nothing at all.

The settings page submits every control it owns as a single payload, and
``ConfigHandler.POST`` walked that payload one key at a time: coerce the value,
then assign it straight into the config the running process reads from
(``local_config[key] = value`` in ``channel/web/api/config.py``). The
``int()`` coercion of a numeric setting raises ``ValueError`` on a value the
browser sent as an empty string, and it raised only *after* an earlier key in
the same payload had already been adopted.

The handler's own ``except`` caught that and returned ``{"status": "error"}``,
so the console showed a rejected save -- but the running agent was already
answering with the newly selected model while ``config.json`` still held the
old one, because the file write is further down and never ran. The save looked
like it had done nothing, on a process that had quietly done something else, and
the next save or restart reverted it without anyone being told.

What is pinned here is that a rejected save is a no-op: not the file on disk,
and not the live config either -- the valid key in the same payload must not be
half-applied on the way to being rejected.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


ORIGINAL = {"model": "old-model", "agent_max_steps": 20}


class RejectedConsoleSaveIsANoOp(unittest.TestCase):
    """One real ``ConfigHandler.POST`` against a config.json in a temp dir.

    ``conf()`` hands back the same dict every time, so anything the handler
    adopts into it is live in the running process for the rest of the test --
    which is exactly the state the defect left behind.
    """

    def setUp(self):
        import channel.web.api.config as config_api

        self.config_api = config_api
        self.data_root = tempfile.mkdtemp(prefix="cow-config-save-")
        self.addCleanup(shutil.rmtree, self.data_root, True)

        self.config_path = os.path.join(self.data_root, "config.json")
        self.original_text = json.dumps(ORIGINAL, indent=4, ensure_ascii=False)
        with open(self.config_path, "w", encoding="utf-8") as handle:
            handle.write(self.original_text)

        self.live = dict(ORIGINAL)

    def _save(self, updates):
        """POST `updates` the way the settings page does, and parse the reply."""
        api = self.config_api
        patches = (
            patch.object(api, "_require_auth", lambda: None),
            patch.object(api.web, "header", lambda *a, **k: None),
            patch.object(api.web, "data", lambda: json.dumps({"updates": updates}).encode()),
            patch.object(api, "conf", lambda: self.live),
            patch.object(api, "get_data_root", lambda: self.data_root),
            patch.object(api, "_read_config_file_for_write", lambda: dict(self.live)),
        )
        for entered in patches:
            entered.start()
            self.addCleanup(entered.stop)

        return json.loads(api.ConfigHandler().POST())

    def _on_disk(self):
        with open(self.config_path, encoding="utf-8") as handle:
            return handle.read()

    def test_a_rejected_value_leaves_the_file_and_the_live_config_alone(self):
        """One valid key, one the int() coercion refuses.

        The whole save is rejected, so the valid key must not survive it: a
        process serving the new model against an unchanged config.json is the
        state this test exists to rule out.
        """
        response = self._save({"model": "new-model", "agent_max_steps": ""})

        # Answered rather than raised, so the console shows a rejected save
        # instead of a 500.
        self.assertEqual(response["status"], "error")
        # The file is byte-for-byte what it was.
        self.assertEqual(self._on_disk(), self.original_text)
        # And the running process is still on the model it was serving.
        self.assertEqual(self.live["model"], "old-model")

    def test_a_save_that_is_accepted_still_lands_in_the_file_and_the_live_config(self):
        """The guard against a save that cannot go wrong because nothing is ever
        applied: the same two keys, both valid, must still take effect."""
        response = self._save({"model": "new-model", "agent_max_steps": 30})

        self.assertEqual(response["status"], "success")
        saved = json.loads(self._on_disk())
        self.assertEqual(saved["model"], "new-model")
        self.assertEqual(saved["agent_max_steps"], 30)
        self.assertEqual(self.live["model"], "new-model")
        self.assertEqual(self.live["agent_max_steps"], 30)


if __name__ == "__main__":
    unittest.main()
