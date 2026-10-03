# encoding:utf-8
"""A capitalised capability tag must survive normalisation, not be dropped.

``normalize_entry`` lowercases each tag and keeps it only if it is one of
``VALID_CAPABILITIES``, but it tested membership on the token *before*
lowercasing it::

    caps = [str(c).strip().lower() for c in caps if str(c).strip() in VALID_CAPABILITIES]

``"TEXT"`` therefore never matched ``"text"`` and was discarded as if it were an
unrecognised tag. A hand-edited ``models.json`` or an API-submitted entry
carrying ``["TEXT", "vision"]`` came back as ``["vision"]`` -- the model kept a
vision tag and lost its text tag.

That is not cosmetic. The text tag is what puts a model in the main chat model
dropdown: the models API filters the merged catalog by capability
(``_apply_catalog``) and the session list does the same
(``"text" in e.get("capabilities")``). And because ``save_catalog`` persists the
normalised entry, the tag was gone from disk too: the next read had nothing left
to restore it from, so a single capitalised tag permanently removed the model
from the chat dropdown until the entry was typed out again.

The empty-set fallback hid this for a while -- a model tagged only ``["TEXT"]``
lost everything and was handed the ``["text"]`` default -- which is why the
mixed case matters most: one surviving tag is enough to skip that fallback.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import model_catalog


class NormalizeEntryCapabilityCaseTest(unittest.TestCase):
    """``normalize_entry`` compares the tag it keeps, not the tag it was given."""

    def test_a_capitalised_tag_survives_next_to_a_lowercase_one(self):
        """The reported case: ``["TEXT", "vision"]`` keeps both tags."""
        entry = model_catalog.normalize_entry(
            {"name": "glm-5.3", "capabilities": ["TEXT", "vision"]})

        self.assertEqual(["text", "vision"], entry["capabilities"])

    def test_mixed_case_and_surrounding_whitespace_are_normalised(self):
        """Casing and padding are both cosmetic; neither may drop a tag."""
        entry = model_catalog.normalize_entry(
            {"name": "glm-5.3", "capabilities": [" Vision ", "TEXT", "\ttext\n"]})

        self.assertEqual(["vision", "text", "text"], entry["capabilities"])

    def test_an_unknown_tag_is_still_dropped_silently(self):
        """The documented silent drop of an unrecognised tag is unchanged.

        ``normalize_entry`` keeps a hand-edited entry loadable rather than
        rejecting it whole; that stays true, it is only the comparison that was
        wrong.
        """
        entry = model_catalog.normalize_entry(
            {"name": "glm-5.3", "capabilities": ["text", "telepathy"]})

        self.assertEqual(["text"], entry["capabilities"])


class SavedCatalogCapabilityCaseTest(unittest.TestCase):
    """What ``save_catalog`` writes is what every later read has to work from."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cow_catalog_case_")
        # The store lives at <shared workspace>/system/models.json; point that
        # workspace at a temp dir so the test never touches a real one.
        from common import state_dir
        self._store = os.path.join(self.tmp, "system", "models.json")
        self.patcher = patch.object(
            state_dir, "models_catalog_file", return_value=state_dir.Path(self._store))
        self.patcher.start()
        # _load caches the store in a module global; a leftover would hide the
        # file this test just wrote.
        model_catalog._invalidate()

    def tearDown(self):
        self.patcher.stop()
        model_catalog._invalidate()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _stored_entry(self, provider_id="zhipu"):
        """The entry as it sits in ``system/models.json`` after a save."""
        with open(self._store, encoding="utf-8") as f:
            return json.load(f)["providers"][provider_id]["overrides"][0]

    def test_a_saved_capitalised_tag_is_persisted_in_lower_case(self):
        """The tag has to survive the write, not only the caller's copy.

        This is the part that made the loss permanent: the console saves the
        whole catalog on every edit, so a tag dropped here was dropped from disk
        for good.
        """
        model_catalog.save_catalog(
            "zhipu", [{"name": "glm-5.3", "capabilities": ["TEXT", "vision"]}], [])

        self.assertEqual(["text", "vision"], self._stored_entry()["capabilities"])

    def test_a_saved_capitalised_tag_still_reads_back_as_a_chat_model(self):
        """The saved model keeps the text tag the chat dropdown filters on."""
        model_catalog.save_catalog(
            "zhipu", [{"name": "glm-5.3", "capabilities": ["TEXT", "vision"]}], [])

        entry = model_catalog.get_catalog("zhipu")[0]
        self.assertIn("text", entry.get("capabilities") or [])
        # The same test the session list and the models API run over an entry.
        self.assertIn("glm-5.3", [
            e["name"] for e in model_catalog.get_catalog("zhipu")
            if "text" in (e.get("capabilities") or [])])

    def test_a_capitalised_only_tag_does_not_lean_on_the_default(self):
        """``["TEXT"]`` alone used to survive only as the empty-set fallback.

        Once the tag is matched on its own it has to be there in its own right,
        otherwise a model whose real tags are all capitalised is still one edit
        away from being reclassified.
        """
        model_catalog.save_catalog(
            "zhipu", [{"name": "glm-5.3", "capabilities": ["TEXT"]}], [])

        self.assertEqual(["text"], self._stored_entry()["capabilities"])

    def test_a_capitalised_entry_survives_a_reload_of_the_store(self):
        """A second read of the file must not normalise the tag away."""
        model_catalog.save_catalog(
            "zhipu", [{"name": "glm-5.3", "capabilities": ["VISION", "Text"]}], [])
        model_catalog._invalidate()

        entry = model_catalog.get_catalog("zhipu")[0]
        self.assertEqual(["vision", "text"], entry["capabilities"])


if __name__ == "__main__":
    unittest.main()
