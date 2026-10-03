# encoding:utf-8
"""An unreadable environment override must be rejected, not stored as a string.

``load_config`` overrides every registered config key from the environment with
``ast.literal_eval``. A value that is not a Python literal --
``REQUEST_TIMEOUT=180s``, ``AGENT_MAX_CONTEXT_TURNS=30 turns`` -- makes
``literal_eval`` raise, and the ``except`` branch then stored the raw *string*
for a key ``available_setting`` documents as an int. Startup said nothing about
it.

The mismatch only surfaces somewhere else entirely, and as a different exception
class each time, so the environment typo is nowhere near the traceback: the web
console re-reads the very same keys through ``int(value)`` when the settings
page is saved (``channel/web/api/config.py``), so one typo in the environment
left the console unable to save any setting at all, while the chat service's
``max_turns // 2`` raised ``TypeError`` about ``str`` and ``int`` rather than the
``ValueError`` the value actually was.

These tests pin the minimal behaviour: a value that cannot be read as the type
its key is documented as is *rejected* -- the template/configured value stands
and a warning names the key. The value is never part of that warning, because
any registered key may hold an api key or a token. A value that does read as the
documented type is still applied, unchanged.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_module


class EnvOverrideRejectedValueTest(unittest.TestCase):
    """Load the config with a malformed environment value set for one key."""

    def _load_with_env(self, **env):
        """Return the loaded config with ``env`` applied on top of a clean one.

        ``COW_DATA_DIR`` points at an empty directory, so there is no
        ``config.json`` to read and ``load_config`` falls back to
        ``config-template.json`` -- the same fallback a fresh env-only
        deployment gets.
        """
        data_dir = tempfile.mkdtemp(prefix="cow-env-override-")
        environ = {"COW_DATA_DIR": data_dir}
        environ.update(env)
        previous = config_module.config
        try:
            with patch.dict(os.environ, environ, clear=False):
                config_module.load_config()
                return config_module.conf()
        finally:
            config_module.config = previous
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_int_override_with_a_unit_suffix_is_rejected_not_stored_as_text(self):
        """``REQUEST_TIMEOUT=180s`` must leave the documented int in place.

        Before the fix the raw ``"180s"`` was stored, which is what the console's
        ``int(value)`` then choked on when the settings page was saved. The key is
        absent from config-template.json, so "left in place" means the key is
        never created and every reader's own default (``conf().get(key, 180)``)
        answers -- which is how all of them read it.
        """
        conf = self._load_with_env(REQUEST_TIMEOUT="180s")
        timeout = conf.get("request_timeout", 180)

        self.assertEqual(180, timeout)
        self.assertNotIsInstance(timeout, str)

    def test_int_override_with_trailing_words_never_becomes_a_string(self):
        """The same rejection for the key that drives context trimming.

        ``agent_max_context_turns`` is read back as ``max_turns // 2`` by the
        chat service, so a string there is a ``TypeError`` mid-turn rather than a
        typo reported at startup.
        """
        conf = self._load_with_env(AGENT_MAX_CONTEXT_TURNS="30 turns")

        self.assertNotIsInstance(conf.get("agent_max_context_turns"), str)
        self.assertEqual(30, conf.get("agent_max_context_turns"))

    def test_rejected_override_is_reported_naming_only_the_key(self):
        """The skipped key is named, and the value never reaches the log.

        Every registered key may carry an api key or a token, so the warning has
        to be actionable (``which setting did I mistype?``) without repeating the
        value the operator just exported.
        """
        secret_ish = "180s-s3cr3t-do-not-log"

        with self.assertLogs("log", level="WARNING") as captured:
            self._load_with_env(REQUEST_TIMEOUT=secret_ish)

        reported = "\n".join(captured.output)
        self.assertIn("request_timeout", reported)
        self.assertNotIn(secret_ish, reported)

    def test_bool_override_that_is_not_a_bool_word_is_rejected(self):
        """``GROUP_AT_OFF=yes`` is rejected, not coerced with ``bool()``.

        ``bool("yes")`` is ``True``, so a permissive coercion would read an
        unrecognised word as "on" and quietly enable group @-mention triggering.
        The documented default is ``False``, so rejecting is observable here.
        """
        conf = self._load_with_env(GROUP_AT_OFF="yes")

        self.assertIs(False, conf.get("group_at_off", False))

    def test_float_override_with_a_unit_suffix_is_rejected(self):
        """``TEMPERATURE=0.3`` works, ``TEMPERATURE=warm`` does not."""
        ok = self._load_with_env(TEMPERATURE="0.3")
        self.assertEqual(0.3, ok.get("temperature"))

        rejected = self._load_with_env(TEMPERATURE="warm")
        self.assertEqual(0.9, rejected.get("temperature", 0.9))

    def test_a_plain_int_override_is_still_applied(self):
        """The rejection path must not swallow values that are already fine."""
        conf = self._load_with_env(REQUEST_TIMEOUT="90")

        self.assertEqual(90, conf.get("request_timeout"))

    def test_a_string_override_keeps_the_raw_value(self):
        """Keys documented as strings keep today's behaviour.

        Most registered keys are strings (``model``, api bases, api keys), and
        their values are not Python literals either -- ``MODEL=gpt-4o`` reaches
        the same ``except`` branch and must still arrive verbatim.
        """
        conf = self._load_with_env(TEXT_TO_VOICE_MODEL="tts-1-hd")

        self.assertEqual("tts-1-hd", conf.get("text_to_voice_model"))

    def test_bool_words_are_still_honoured(self):
        """``SPEECH_RECOGNITION=false`` keeps working, as before."""
        conf = self._load_with_env(SPEECH_RECOGNITION="false")

        self.assertIs(False, conf.get("speech_recognition"))


if __name__ == "__main__":
    unittest.main()
