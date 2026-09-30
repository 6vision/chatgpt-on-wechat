# encoding:utf-8
"""The /uploads/ handler must confine reads to the Agent's own tmp dir.

UploadsHandler guarded its path with a bare prefix comparison::

    full_path = os.path.normpath(os.path.join(upload_dir, file_name))
    if not os.path.abspath(full_path).startswith(os.path.abspath(upload_dir)):
        raise web.notfound()

``str.startswith`` has no separator terminator, so any sibling directory whose
name merely *begins with the same characters* passes the check. The upload dir
is ``<workspace>/tmp``, which makes ``<workspace>/tmp_secrets`` a sibling: with
``file_name="../tmp_secrets/id_rsa"`` normpath collapses to
``<workspace>/tmp_secrets/id_rsa``, that string starts with ``<workspace>/tmp``,
and the file is served verbatim. The same escape needs no ``..`` at all on
Windows, where os.path.join discards the left side for a drive-qualified tail.

It is not only Agent data next door that this reaches. The console binds
127.0.0.1 with no password by default, and every <img src="/uploads/...">, TTS
reply URL and voice bubble goes through this one handler, so anything on the box
-- including the agent's own web_fetch tool aimed at the console -- could read
the file.

The sibling-prefix escape is what these tests pin; the in-tree cases are the
control that stops an over-broad fix from 404-ing every real upload.
"""

import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Deliberately no sys.modules["web"] stub here, unlike the other handler tests.
# A stub's web.application() returns a wsgifunc of None, so whichever test module
# collects first decides whether the real web.py or the stub answers -- and this
# module sorts before every test_web_*, so a stub installed here would be the one
# web_channel.build_app() picked up, breaking the real-server upload tests. The
# handler only reaches for web.input/web.header/web.notfound, and _get() patches
# all three, so the real module is never actually called.
import web


class _NotFound(web.HTTPError):
    """Stands in for web.notfound() so a refusal is unambiguous.

    Subclassing HTTPError mirrors the real web.NotFound, so the handler's
    ``except web.HTTPError: raise`` re-raises it rather than routing it
    through the generic error branch. web.HTTPError.__init__ wants a status and
    headers and writes to web.ctx, none of which mean anything outside a real
    request, so this goes straight to Exception.
    """

    def __init__(self):
        Exception.__init__(self, "404 Not Found")


def _raise_notfound(*args, **kwargs):
    raise _NotFound()


class TestUploadsHandlerPathContainment(unittest.TestCase):
    """UploadsHandler must not serve anything outside <workspace>/tmp."""

    def setUp(self):
        self.tmp_root = tempfile.mkdtemp()
        self.workspace = os.path.join(self.tmp_root, "workspace")
        self.upload_dir = os.path.join(self.workspace, "tmp")
        # The sibling: same characters up to "tmp", then more. This is the
        # directory the bare startswith() let through.
        self.sibling_dir = os.path.join(self.workspace, "tmp_secrets")
        os.makedirs(self.upload_dir)
        os.makedirs(self.sibling_dir)
        os.makedirs(os.path.join(self.upload_dir, "sub"))

        self.inside = os.path.join(self.upload_dir, "voice_reply.png")
        with open(self.inside, "wb") as f:
            f.write(b"in-tree-bytes")
        self.nested_inside = os.path.join(self.upload_dir, "sub", "chart.png")
        with open(self.nested_inside, "wb") as f:
            f.write(b"nested-in-tree-bytes")
        self.escaped = os.path.join(self.sibling_dir, "id_rsa")
        with open(self.escaped, "wb") as f:
            f.write(b"TOP-SECRET")

    def tearDown(self):
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def _get(self, file_name):
        """Drive UploadsHandler.GET the way web_channel routes /uploads/(.*)."""
        from channel.web.api import files as files_api

        with patch.object(files_api, "_require_auth", lambda: None), \
                patch.object(files_api, "_get_upload_dir",
                             lambda agent_id=None: self.upload_dir), \
                patch.object(files_api.web, "input",
                             lambda **kwargs: types.SimpleNamespace(agent_id="")), \
                patch.object(files_api.web, "header", lambda *args, **kwargs: None), \
                patch.object(files_api.web, "notfound", _raise_notfound):
            return files_api.UploadsHandler().GET(file_name)

    # -- the escape ------------------------------------------------------

    def test_a_sibling_sharing_the_tmp_prefix_is_not_served(self):
        """'../tmp_secrets/id_rsa' shares the 'tmp' prefix, so it used to pass."""
        with self.assertRaises(_NotFound):
            self._get(os.path.join("..", "tmp_secrets", "id_rsa"))

    def test_the_escape_also_works_from_a_subdirectory(self):
        """Starting inside tmp/ does not change the outcome."""
        with self.assertRaises(_NotFound):
            self._get(os.path.join("sub", "..", "..", "tmp_secrets", "id_rsa"))

    @unittest.skipUnless(os.name == "nt", "os.path.join only discards the left side for a drive-qualified tail")
    def test_a_drive_qualified_tail_escapes_without_any_dotdot(self):
        r"""'C:\...\tmp_secrets\id_rsa' makes normpath()'s work a no-op.

        ntpath.join returns the second argument outright when it carries its
        own drive letter, so the joined path never mentions upload_dir at all
        and only the prefix comparison stands between the two.
        """
        with self.assertRaises(_NotFound):
            self._get(self.escaped)

    # -- the control: real uploads keep working --------------------------

    def test_a_file_in_the_upload_dir_is_still_served(self):
        self.assertEqual(b"in-tree-bytes", self._get("voice_reply.png"))

    def test_a_file_in_a_subdirectory_of_the_upload_dir_is_still_served(self):
        self.assertEqual(b"nested-in-tree-bytes", self._get(os.path.join("sub", "chart.png")))

    def test_a_dotdot_that_stays_inside_the_upload_dir_is_still_served(self):
        """'sub/../x.png' normalises back into tmp/, so it must not be refused."""
        self.assertEqual(b"in-tree-bytes", self._get(os.path.join("sub", "..", "voice_reply.png")))

    def test_a_dotdot_out_of_the_workspace_is_still_refused(self):
        """The escape the old check did catch must stay caught."""
        with self.assertRaises(_NotFound):
            self._get(os.path.join("..", "..", "outside.txt"))

    def test_a_missing_file_in_the_upload_dir_is_still_a_404(self):
        with self.assertRaises(_NotFound):
            self._get("never-uploaded.png")

    # -- Windows: the check must not turn case-sensitive ------------------

    @unittest.skipUnless(os.name == "nt", "only the Windows filesystem folds case")
    def test_a_case_differed_name_inside_the_upload_dir_is_still_served(self):
        """Containment is about the directory, not about the file's spelling.

        The joined path always begins with the very upload_dir string the
        comparison uses, so the prefix can never differ in case; this guards
        the tail, which Windows resolves case-insensitively.
        """
        self.assertEqual(b"in-tree-bytes", self._get("VOICE_REPLY.PNG"))


if __name__ == "__main__":
    unittest.main()
