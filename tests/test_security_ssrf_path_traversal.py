# encoding:utf-8
"""
Unit tests for security fixes:
  1. Vision tool SSRF protection (issue #2878, #2872)
  2. Skill service path traversal protection (issue #2873)
"""
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub 'requests' if not installed so vision.py can be imported for testing.
if "requests" not in sys.modules:
    _requests_stub = types.ModuleType("requests")
    _requests_stub.get = lambda *a, **k: None
    sys.modules["requests"] = _requests_stub


# =============================================================================
# Vision SSRF tests
# =============================================================================

class TestVisionSSRFValidation(unittest.TestCase):
    """Test that _validate_url_safe blocks internal/private URLs.

    SSRF protection is opt-in (disabled by default); enable it via env for
    the duration of these tests.
    """

    def setUp(self):
        self._prev_ssrf_env = os.environ.get("WEB_SECURITY_SSRF_PROTECTION")
        os.environ["WEB_SECURITY_SSRF_PROTECTION"] = "true"
        from agent.tools.vision.vision import Vision
        self.validate = Vision._validate_url_safe

    def tearDown(self):
        if self._prev_ssrf_env is None:
            os.environ.pop("WEB_SECURITY_SSRF_PROTECTION", None)
        else:
            os.environ["WEB_SECURITY_SSRF_PROTECTION"] = self._prev_ssrf_env

    def test_loopback_ipv4_blocked(self):
        """127.0.0.1 must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.validate("http://127.0.0.1/canary.png")
        self.assertIn("non-public", str(ctx.exception))

    def test_loopback_localhost_blocked(self):
        """localhost must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.validate("http://localhost/canary.png")
        self.assertIn("non-public", str(ctx.exception))

    def test_private_10_network_blocked(self):
        """10.x.x.x RFC1918 must be rejected."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("10.0.0.1", 0)),
            ]
            with self.assertRaises(ValueError) as ctx:
                self.validate("http://internal.corp/image.png")
            self.assertIn("non-public", str(ctx.exception))

    def test_private_172_network_blocked(self):
        """172.16.x.x RFC1918 must be rejected."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("172.16.0.1", 0)),
            ]
            with self.assertRaises(ValueError) as ctx:
                self.validate("http://internal.corp/image.png")
            self.assertIn("non-public", str(ctx.exception))

    def test_private_192_168_blocked(self):
        """192.168.x.x RFC1918 must be rejected."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("192.168.1.1", 0)),
            ]
            with self.assertRaises(ValueError) as ctx:
                self.validate("http://router.local/image.png")
            self.assertIn("non-public", str(ctx.exception))

    def test_link_local_blocked(self):
        """169.254.x.x (link-local / cloud metadata) must be rejected."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("169.254.169.254", 0)),
            ]
            with self.assertRaises(ValueError) as ctx:
                self.validate("http://metadata.google.internal/image.png")
            self.assertIn("non-public", str(ctx.exception))

    def test_ipv6_loopback_blocked(self):
        """::1 (IPv6 loopback) must be rejected."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (10, 1, 6, "", ("::1", 0, 0, 0)),
            ]
            with self.assertRaises(ValueError) as ctx:
                self.validate("http://[::1]/image.png")
            self.assertIn("non-public", str(ctx.exception))

    def test_public_url_allowed(self):
        """A URL resolving to a public IP should pass validation."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("151.101.1.140", 0)),
            ]
            # Should not raise
            self.validate("https://cdn.example.com/image.png")

    def test_no_hostname_rejected(self):
        """A URL with no host must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.validate("http:///path/to/image.png")
        self.assertIn("no hostname", str(ctx.exception))

    def test_non_http_scheme_rejected(self):
        """file:// and ftp:// schemes must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.validate("file:///etc/passwd")
        self.assertIn("scheme", str(ctx.exception))

    def test_dns_failure_rejected(self):
        """Unresolvable hostname must be rejected."""
        import socket as sock_mod
        with patch("socket.getaddrinfo", side_effect=sock_mod.gaierror("Name does not resolve")):
            with self.assertRaises(ValueError) as ctx:
                self.validate("http://nonexistent.invalid/img.png")
            self.assertIn("Cannot resolve", str(ctx.exception))


# =============================================================================
# Skill service path traversal tests
# =============================================================================

class TestSkillServicePathTraversal(unittest.TestCase):
    """Test that _safe_skill_dir blocks path traversal attempts."""

    def setUp(self):
        self.tmp_root = tempfile.mkdtemp()
        # Create a minimal SkillManager mock with custom_dir set.
        from agent.skills.service import SkillService
        mock_manager = MagicMock()
        mock_manager.custom_dir = self.tmp_root
        self.svc = SkillService(mock_manager)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def test_normal_name_allowed(self):
        """A simple name like 'my-skill' should produce a valid path."""
        result = self.svc._safe_skill_dir("my-skill")
        expected = os.path.realpath(os.path.join(self.tmp_root, "my-skill"))
        self.assertEqual(result, expected)

    def test_dotdot_traversal_blocked(self):
        """'../escaped' must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.svc._safe_skill_dir("../escaped")
        self.assertIn("path traversal", str(ctx.exception))

    def test_nested_dotdot_blocked(self):
        """'foo/../../escaped' must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.svc._safe_skill_dir("foo/../../escaped")
        self.assertIn("path traversal", str(ctx.exception))

    def test_absolute_path_blocked(self):
        """'/tmp/evil' must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.svc._safe_skill_dir("/tmp/evil")
        self.assertIn("path traversal", str(ctx.exception))

    def test_backslash_path_blocked(self):
        r"""'\\server\share' must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.svc._safe_skill_dir("\\server\\share")
        self.assertIn("path traversal", str(ctx.exception))

    def test_empty_name_blocked(self):
        """Empty name must be rejected."""
        with self.assertRaises(ValueError):
            self.svc._safe_skill_dir("")

    def test_whitespace_only_blocked(self):
        """Whitespace-only name must be rejected."""
        with self.assertRaises(ValueError):
            self.svc._safe_skill_dir("   ")

    def test_subdir_name_allowed(self):
        """A name with a forward slash but no traversal is allowed if it stays in root."""
        # e.g. "category/skill-name" is a valid nested skill directory
        result = self.svc._safe_skill_dir("category/skill-name")
        expected = os.path.realpath(os.path.join(self.tmp_root, "category/skill-name"))
        self.assertEqual(result, expected)


class TestSkillServiceFilePathTraversal(unittest.TestCase):
    """Test that the per-file paths in an add payload cannot escape the skills root.

    The skill *name* is validated by _safe_skill_dir (issue #2873), but every
    entry in ``payload["files"]`` also carries a ``path`` that is joined onto
    the install directory, so it needs the same containment check.
    """

    def setUp(self):
        self.tmp_root = tempfile.mkdtemp()
        self.skills_root = os.path.join(self.tmp_root, "skills")
        os.makedirs(self.skills_root)
        from agent.skills.service import SkillService
        mock_manager = MagicMock()
        mock_manager.custom_dir = self.skills_root
        self.svc = SkillService(mock_manager)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def _add_url_with_path(self, rel_path):
        """Run _add_url with a single file entry, writing a marker to each dest."""
        written = []

        def fake_download(url, dest):
            written.append(dest)
            parent = os.path.dirname(dest)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(dest, "w") as f:
                f.write("pwned")

        with patch.object(self.svc, "_download_file", side_effect=fake_download):
            self.svc._add_url("innocent", {
                "name": "innocent",
                "files": [{"url": "https://example.com/a", "path": rel_path}],
            })
        return written

    def test_relative_file_path_allowed(self):
        """A plain nested path stays inside the skill directory."""
        written = self._add_url_with_path("scripts/run.py")
        self.assertEqual(1, len(written))
        self.assertEqual(
            os.path.realpath(self.skills_root),
            os.path.commonpath([os.path.realpath(self.skills_root), os.path.realpath(written[0])]),
        )
        with open(os.path.join(self.skills_root, "innocent", "scripts", "run.py")) as installed:
            self.assertEqual("pwned", installed.read())

    def test_dotdot_file_path_blocked(self):
        """'../../escaped.py' must be rejected before anything is downloaded."""
        with self.assertRaises(ValueError) as ctx:
            self._add_url_with_path("../../escaped.py")
        self.assertIn("path traversal", str(ctx.exception))
        self.assertFalse(os.path.exists(os.path.join(self.tmp_root, "escaped.py")))

    def test_backslash_file_path_blocked(self):
        r"""'..\..\escaped.py' must be rejected (Windows separators)."""
        with self.assertRaises(ValueError) as ctx:
            self._add_url_with_path("..\\..\\escaped.py")
        self.assertIn("path traversal", str(ctx.exception))

    def test_absolute_posix_file_path_blocked(self):
        """An absolute POSIX path must be rejected, not silently honoured."""
        with self.assertRaises(ValueError) as ctx:
            self._add_url_with_path("/tmp/cow-evil-marker.py")
        self.assertIn("path traversal", str(ctx.exception))

    def test_absolute_native_file_path_blocked(self):
        """An absolute path outside the skills root must be rejected."""
        outside = os.path.join(self.tmp_root, "outside", "evil.py")
        with self.assertRaises(ValueError) as ctx:
            self._add_url_with_path(outside)
        self.assertIn("path traversal", str(ctx.exception))
        self.assertFalse(os.path.exists(outside))

    def test_midpath_dotdot_blocked(self):
        """'sub/../../sibling.py' escapes the skill dir even while inside the root."""
        with self.assertRaises(ValueError) as ctx:
            self._add_url_with_path("sub/../../sibling.py")
        self.assertIn("path traversal", str(ctx.exception))
        self.assertFalse(os.path.exists(os.path.join(self.skills_root, "sibling.py")))

    def test_traversal_aborts_before_download(self):
        """No file is fetched at all when an entry is unsafe."""
        calls = []

        def fake_download(url, dest):
            calls.append(url)

        with patch.object(self.svc, "_download_file", side_effect=fake_download):
            with self.assertRaises(ValueError):
                self.svc._add_url("innocent", {
                    "name": "innocent",
                    "files": [{"url": "https://example.com/evil", "path": "../../evil.py"}],
                })
        self.assertEqual([], calls)

    def test_safe_file_path_rejects_root_itself(self):
        """A path resolving to the install dir itself is not a valid file target."""
        with self.assertRaises(ValueError):
            self.svc._safe_file_path(self.skills_root, ".")


if __name__ == "__main__":
    unittest.main()
