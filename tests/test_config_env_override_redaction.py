# encoding:utf-8

"""The environment-override log line wrote every credential in cleartext.

``load_config`` lets an env var override any registered setting, which is how a
platform like Railway or a Docker deploy supplies its secrets. On the way it
logged the win::

    logger.info("[INIT] override config by environ args: {}={}".format(name, value))

``value`` is the raw environment string, so ``DINGTALK_CLIENT_SECRET``,
``OPEN_AI_API_KEY`` and ``LINKAI_API_KEY`` all landed in ``run.log`` in full. Every
other config line in this module already goes through ``drag_sensitive``
(the config-str dump at line 509 and the loaded-config dump at line 614), so
this one line was the outlier -- and ``run.log`` is what users paste into bug
reports.

The masking helper keys off the *name*: ``_mask_sensitive_recursive`` masks values
whose key contains ``key`` or ``secret``. So the fix routes this line through the
same helper, which is what keeps the masking policy in one place instead of
growing a second, subtly different one here.

The tests below drive the real ``load_config`` with an env override in place and
read back what the logger was handed: the secret must be gone, the name that
identifies *which* setting was overridden must stay (that is the part that makes
the line useful for debugging), and a non-secret override must be untouched.
"""

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_module

# Registered settings, so the env var is actually applied rather than skipped.
SECRET_KEY = "dingtalk_client_secret"
SECRET_ENV = "DINGTALK_CLIENT_SECRET"
SECRET_VALUE = "sentinel-client-secret-9f2b41aa"

# The masking helper keys off the *name* ("key" or "secret" in it), so the
# control case has to be a registered setting with neither substring in its
# name. "group_chat_keyword" does not qualify: "keyword" contains "key", so the
# helper masks it by design.
PLAIN_KEY = "cow_lang"
PLAIN_ENV = "COW_LANG"
PLAIN_VALUE = "sentinel-plain-value-7731"


class _Collector(logging.Handler):
    """Gather what the ``log`` logger was handed.

    ``common.log`` keeps a reference to the stdout it saw at import time and sets
    ``propagate = False``, so reading the test's own stdout cannot show whether
    the value was routed through the logger at all.
    """

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _load_with_overrides(env):
    """Run the real ``load_config`` with ``env`` applied, return the log text.

    ``conftest`` wraps ``load_config`` at session scope to redirect
    ``agent_workspace``; that wrapper calls the real function, so calling the
    module attribute keeps the redirect *and* exercises the real override loop.

    The override writes into the process-wide config singleton, so the previous
    value of every touched key is restored afterwards -- otherwise a secret
    would stay in the live config for the rest of the run, and a language
    override would leak into unrelated tests.
    """
    collector = _Collector()
    log = logging.getLogger("log")
    previous_env = {name: os.environ.get(name) for name in env}
    live = config_module.conf()
    previous_cfg = {name: live.get(name) for name in env.values()}
    log.addHandler(collector)
    try:
        for name, value in env.items():
            os.environ[name] = value
        config_module.load_config()
    finally:
        log.removeHandler(collector)
        for name, value in previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        for name, value in previous_cfg.items():
            if value is None:
                live.pop(name, None)
            else:
                live[name] = value
    return "\n".join(collector.messages)


class TestEnvOverrideDoesNotLogSecrets(unittest.TestCase):
    """The credential must not reach the log; the setting name must."""

    def test_secret_override_value_is_not_logged(self):
        """The reported defect: the raw secret reached ``run.log``."""
        logged = _load_with_overrides({SECRET_ENV: SECRET_VALUE})

        self.assertIn(SECRET_ENV.lower(), logged,
                      "the overridden setting's name should still be logged")
        self.assertNotIn(SECRET_VALUE, logged,
                         "the environment override value reached the log in cleartext")

    def test_a_second_secret_key_is_also_masked(self):
        """The leak is not specific to one provider's setting name."""
        logged = _load_with_overrides({"OPEN_AI_API_KEY": "sentinel-openai-key-5566"})

        self.assertIn("open_ai_api_key", logged)
        self.assertNotIn("sentinel-openai-key-5566", logged)

    def test_the_setting_name_is_still_logged(self):
        """The line is only useful if it says *what* was overridden.

        This is what a maintainer reads to answer "did my env var reach the
        config at all?", so masking must not take the name with it. Every
        override line is searched rather than just the first, because the
        ambient environment can supply overrides of its own.
        """
        logged = _load_with_overrides({SECRET_ENV: SECRET_VALUE})

        override_lines = [line for line in logged.splitlines()
                          if "override config by environ" in line]
        self.assertTrue(override_lines, "the override line was not logged at all")
        self.assertTrue(
            any(SECRET_ENV.lower() in line for line in override_lines),
            "the overridden setting's name was not logged: {}".format(override_lines),
        )

    def test_non_secret_value_is_still_logged_verbatim(self):
        """Masking everything would destroy the line's debugging value."""
        logged = _load_with_overrides({PLAIN_ENV: PLAIN_VALUE})

        self.assertIn(PLAIN_ENV.lower(), logged)
        self.assertIn(PLAIN_VALUE, logged,
                      "a non-secret override must still be readable in the log")

    def test_the_override_is_still_applied_to_the_config(self):
        """The point of the line was never the point: the override must work.

        Masking the log must not change what the config ends up holding.
        """
        _load_with_overrides({SECRET_ENV: SECRET_VALUE})

        self.assertEqual(config_module.conf().get(SECRET_KEY), SECRET_VALUE,
                         "the environment override stopped being applied")


if __name__ == "__main__":
    unittest.main()
