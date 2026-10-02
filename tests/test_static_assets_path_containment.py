# encoding:utf-8
"""The /assets/ handler must confine reads to the static/ directory.

A bare startswith() check let a sibling sharing the prefix through: static_backup/
and static.old/ both begin with the characters of static/, so a request for
../static_backup/secret.txt normalised to a path that still satisfied the
comparison and was served. The console's static/ holds no secrets, but the
directory it sits in does -- and the same prefix test was already fixed for the
/uploads/ handler, which this now matches.
"""

import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Deliberately no sys.modules["web"] stub here, for the reason spelled out in
# test_uploads_path_containment.py: a stub installed by this module would be the
# one web_channel.build_app() picked up. _get() patches everything the handler
# reaches for, so the real module is never actually called.
import web


class _NotFound(web.HTTPError):
    """Stands in for web.notfound() so a refusal is unambiguous.

    Subclassing HTTPError mirrors the real web.NotFound, so the handler's
    ``except web.HTTPError: raise`` re-raises it rather than routing it through
    the generic error branch. web.HTTPError.__init__ wants a status and headers
    and writes to web.ctx, none of which mean anything outside a real request,
    so this goes straight to Exception.
    """

    def __init__(self):
        Exception.__init__(self, "404 Not Found")


def _raise_notfound(*args, **kwargs):
    raise _NotFound()


class TestAssetsHandlerPathContainment(unittest.TestCase):
    """AssetsHandler must not serve anything outside web/static/."""

    def setUp(self):
        self.tmp_root = tempfile.mkdtemp()
        self.web_dir = os.path.join(self.tmp_root, "channel", "web")
        self.static_dir = os.path.join(self.web_dir, "static")
        os.makedirs(self.static_dir)
        # The handler derives web_dir from its own __file__, so point that at
        # the throwaway tree instead of touching the checkout's static/.
        self.fake_module_file = os.path.join(
            self.web_dir, "api", "pages.py"
        )
        os.makedirs(os.path.dirname(self.fake_module_file))

        self.inside = os.path.join(self.static_dir, "console.css")
        with open(self.inside, "wb") as f:
            f.write(b"in-tree-bytes")

        # The sibling: same characters up to "static", then more. This is the
        # directory the bare startswith() let through.
        self.sibling_dir = os.path.join(self.web_dir, "static_backup")
        os.makedirs(self.sibling_dir)
        self.escaped = os.path.join(self.sibling_dir, "secret.txt")
        with open(self.escaped, "wb") as f:
            f.write(b"TOP-SECRET")

    def tearDown(self):
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def _get(self, file_path):
        """Drive AssetsHandler.GET the way web_channel routes /assets/(.*)."""
        from channel.web.api import pages as pages_api

        with patch.object(pages_api, "__file__", self.fake_module_file), \
                patch.object(pages_api.web, "header", lambda *args, **kwargs: None), \
                patch.object(pages_api.web, "ctx", types.SimpleNamespace(
                    get=lambda *args, **kwargs: {})), \
                patch.object(pages_api.web, "notfound", _raise_notfound):
            return pages_api.AssetsHandler().GET(file_path)

    # -- the escape ------------------------------------------------------

    def test_a_sibling_sharing_the_static_prefix_is_not_served(self):
        """'../static_backup/secret.txt' shares the 'static' prefix."""
        with self.assertRaises(_NotFound):
            self._get(os.path.join("..", "static_backup", "secret.txt"))

    def test_a_path_named_after_the_sibling_is_not_served(self):
        """'static_backup/secret.txt' lands inside static/, where no such file is."""
        with self.assertRaises(_NotFound):
            self._get(os.path.join("static_backup", "secret.txt"))

    @unittest.skipUnless(os.name == "nt", "os.path.join only discards the left side for a drive-qualified tail")
    def test_a_drive_qualified_tail_escapes_without_any_dotdot(self):
        r"""'C:\...\static_backup\secret.txt' makes normpath()'s work a no-op.

        ntpath.join returns the second argument outright when it carries its
        own drive letter, so the joined path never mentions static_dir at all
        and only the prefix comparison stands between the two.
        """
        with self.assertRaises(_NotFound):
            self._get(self.escaped)

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_a_symlink_out_of_the_static_dir_is_not_followed(self):
        os.symlink(self.escaped, os.path.join(self.static_dir, "link.css"))
        with self.assertRaises(_NotFound):
            self._get("link.css")

    # -- the control: real assets keep working ----------------------------

    def test_a_file_in_the_static_dir_is_still_served(self):
        self.assertEqual(b"in-tree-bytes", self._get("console.css"))

    def test_a_dotdot_that_stays_inside_the_static_dir_is_still_served(self):
        """A 'js/../console.css' normalises back into static/, so keep serving it."""
        self.assertEqual(
            b"in-tree-bytes", self._get(os.path.join("js", "..", "console.css"))
        )

    def test_a_dotdot_out_of_the_static_dir_is_still_refused(self):
        """The escape the old check did catch must stay caught."""
        with self.assertRaises(_NotFound):
            self._get(os.path.join("..", "..", "outside.txt"))

    def test_a_missing_file_in_the_static_dir_is_still_a_404(self):
        with self.assertRaises(_NotFound):
            self._get("never-shipped.css")

    def test_the_real_console_assets_are_still_served(self):
        """Containment must not break the assets the console actually loads."""
        from unittest.mock import patch

        from channel.web.core import template

        import channel.web.api.pages as pages_api

        sent = []
        page = template.render("chat.html")
        import re

        scripts = re.findall(r'<script defer src="/assets/(js/[^"?]+)(?:\?[^"?]*)?', page)
        self.assertTrue(scripts, "expected the console page to reference scripts")
        with patch.object(pages_api.web, "header",
                          lambda name, value=None: sent.append((name.lower(), value))):
            handler = pages_api.AssetsHandler()
            for script in scripts:
                del sent[:]
                self.assertTrue(handler.GET(script), script)
                content_type = dict(sent).get("content-type", "")
                self.assertIn("javascript", content_type, (script, content_type))


if __name__ == "__main__":
    unittest.main()
