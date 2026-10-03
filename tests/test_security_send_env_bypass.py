# encoding:utf-8
"""The Send tool refuses credential paths, like the other file tools.

HOME is redirected to a temp dir so the real credential file is never touched.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.send.send import Send
from agent.tools.utils.credentials import is_credential_path

_DENIED = "Access denied"
_SECRET = "sk-SECRET-canary-value"


class _TempHomeCase(unittest.TestCase):
    """Gives each test an isolated HOME holding a credential file.

    On Windows ``ntpath.expanduser`` resolves the home directory from
    USERPROFILE and ignores HOME, so both are redirected -- otherwise the guard
    would keep comparing against the real ~/.cow/.env and these assertions
    would not exercise the redirect at all.
    """

    _HOME_VARS = ("HOME", "USERPROFILE")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._real_home = {name: os.environ.get(name) for name in self._HOME_VARS}
        for name in self._HOME_VARS:
            os.environ[name] = self.tmp

        os.makedirs(os.path.join(self.tmp, ".cow"))
        self.env_path = os.path.join(self.tmp, ".cow", ".env")
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write(f"OPENAI_API_KEY={_SECRET}\nANTHROPIC_KEY=sk-ant-other\n")

        self.workspace = os.path.join(self.tmp, "cow")
        os.makedirs(self.workspace)
        self.config = {"cwd": self.workspace}

    def tearDown(self):
        for name, value in self._real_home.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestSendCredentialGuard(_TempHomeCase):
    """The send tool must refuse credential paths like the other file tools."""

    def test_direct_path_blocked(self):
        result = Send(self.config).execute({"path": self.env_path})
        self.assertEqual(result.status, "error")
        self.assertIn(_DENIED, str(result.result))

    def test_tilde_path_blocked(self):
        result = Send(self.config).execute({"path": "~/.cow/.env"})
        self.assertEqual(result.status, "error")
        self.assertIn(_DENIED, str(result.result))

    def test_secret_never_reaches_the_result(self):
        """The whole point of the guard: the key must not leave in the payload."""
        result = Send(self.config).execute({"path": self.env_path})
        self.assertNotIn(_SECRET, str(result.result))

    def test_refusal_precedes_the_existence_check(self):
        """A *missing* credential path reads as denied, not as missing.

        Pins the ordering: were the guard after the exists() check, this would
        surface as "File not found" instead of the refusal the other tools give.
        The path stays a credential path, so removing the file is enough.
        """
        os.remove(self.env_path)
        self.assertTrue(is_credential_path(self.env_path))

        result = Send(self.config).execute({"path": self.env_path})
        self.assertEqual(result.status, "error")
        self.assertIn(_DENIED, str(result.result))
        self.assertNotIn("not found", str(result.result).lower())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink not supported")
    def test_symlink_blocked(self):
        """A symlink resolving to the credential file must not be a way in."""
        link = os.path.join(self.workspace, "innocent.txt")
        try:
            os.symlink(self.env_path, link)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create symlink in this environment")
        result = Send(self.config).execute({"path": link})
        self.assertEqual(result.status, "error")
        self.assertIn(_DENIED, str(result.result))

    # ---- control: ordinary sends are untouched --------------------------

    def test_ordinary_file_still_sent(self):
        target = os.path.join(self.workspace, "note.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("hello world\n")
        result = Send(self.config).execute({"path": "note.txt"})
        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["type"], "file_to_send")

    def test_remote_url_still_passes_through(self):
        """Remote URLs never touch the filesystem and must still pass."""
        result = Send(self.config).execute({"path": "https://example.com/pic.png"})
        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["url"], "https://example.com/pic.png")

    def test_ordinary_path_not_treated_as_credential(self):
        """No over-blocking: an ordinary workspace path is not a credential."""
        self.assertFalse(is_credential_path(os.path.join(self.workspace, "a.txt")))
        self.assertFalse(
            is_credential_path(os.path.join(self.tmp, ".cow", "config.json"))
        )


if __name__ == "__main__":
    unittest.main()
