# encoding:utf-8
"""
Regression tests for the LinkAI file download's HTTP status handling.

``link_ai_bot._download_file`` wrote ``response.content`` to disk without ever
looking at the status code. The URLs it is handed are signed, expiring links, so
the common failure is not a connection error but a perfectly well-formed
response carrying an error status: a 404 or 403 whose body is an HTML error
page. That page was saved under the document's own filename and returned as a
successful path, so ``_send_image`` handed the user a ``FILE`` reply containing
an HTML error page named ``report.pdf`` -- and left it sitting in the tmp dir
for anything downstream to pick up.

The download must check the status before writing, matching the
``raise_for_status()`` idiom the rest of the codebase already uses for fetches.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.linkai import link_ai_bot

# What a CDN or signed-URL host returns once the link has expired.
ERROR_PAGE = (
    b"<!DOCTYPE html><html><head><title>403 Forbidden</title></head>"
    b"<body><h1>Access denied</h1><p>This link has expired.</p></body></html>"
)


class _FakeResponse:
    """Minimal stand-in for a requests Response that honours raise_for_status."""

    def __init__(self, status_code, content):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if 400 <= self.status_code < 600:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class DownloadTestCase(unittest.TestCase):
    """Points the tmp dir at a scratch folder and stubs the HTTP layer."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        patcher = patch.object(
            link_ai_bot.state_dir, "tmp_dir", return_value=self.tmp_dir
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def _get(self, status_code, content):
        """Install a stub requests.get returning the given response."""
        patcher = patch.object(
            link_ai_bot.requests, "get",
            return_value=_FakeResponse(status_code, content),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _written(self):
        return sorted(p.name for p in self.tmp_dir.iterdir())


class TestDownloadRejectsErrorStatus(DownloadTestCase):
    """An error response must never reach the output path."""

    def test_404_is_not_written(self):
        """A 404 body must not be saved as the requested document."""
        self._get(404, ERROR_PAGE)

        result = link_ai_bot._download_file("https://files.example.com/report.pdf")

        self.assertIsNone(result)
        self.assertEqual(self._written(), [])

    def test_403_is_not_written(self):
        """An expired signed link usually answers 403."""
        self._get(403, ERROR_PAGE)

        result = link_ai_bot._download_file("https://files.example.com/report.pdf")

        self.assertIsNone(result)
        self.assertEqual(self._written(), [])

    def test_500_is_not_written(self):
        """A gateway error is equally not a file."""
        self._get(500, ERROR_PAGE)

        result = link_ai_bot._download_file("https://files.example.com/report.pdf")

        self.assertIsNone(result)
        self.assertEqual(self._written(), [])

    def test_error_page_never_reuses_the_document_name(self):
        """The HTML page must not land under the document's own filename."""
        self._get(404, ERROR_PAGE)

        link_ai_bot._download_file("https://files.example.com/report.pdf")

        self.assertNotIn("report.pdf", self._written())

    def test_successful_download_still_writes_the_file(self):
        """The happy path is untouched: bytes land on disk and the path returns."""
        payload = b"%PDF-1.7 real document"
        self._get(200, payload)

        result = link_ai_bot._download_file("https://files.example.com/report.pdf")

        self.assertIsNotNone(result)
        self.assertEqual(Path(result).name, "report.pdf")
        self.assertEqual(Path(result).read_bytes(), payload)
        self.assertEqual(self._written(), ["report.pdf"])


class TestSendImageSkipsFailedDownload(DownloadTestCase):
    """The caller must not turn a failed download into a FILE reply."""

    def _send(self, url):
        from config import conf

        class _Channel:
            def __init__(self):
                self.sent = []

            def send(self, reply, context):
                self.sent.append(reply)

        with patch.dict(conf(), {"max_media_send_count": 10, "media_send_interval": 0}, clear=False):
            channel = _Channel()
            link_ai_bot.LinkAIBot._send_image(
                link_ai_bot.LinkAIBot.__new__(link_ai_bot.LinkAIBot),
                channel, None, [url],
            )
        return channel.sent

    def test_failed_document_download_sends_nothing(self):
        """A .pdf that 404s must not be delivered as a FILE reply."""
        self._get(404, ERROR_PAGE)

        sent = self._send("https://files.example.com/report.pdf")

        self.assertEqual(sent, [])
        self.assertEqual(self._written(), [])

    def test_successful_document_download_still_sends_file_reply(self):
        """The existing behaviour for a real document is preserved."""
        self._get(200, b"%PDF-1.7 real document")

        sent = self._send("https://files.example.com/report.pdf")

        self.assertEqual([r.type.name for r in sent], ["FILE"])
        self.assertEqual(self._written(), ["report.pdf"])

    def test_image_urls_do_not_hit_the_downloader(self):
        """Images still go out as URL replies; only file types are downloaded."""
        sent = self._send("https://files.example.com/picture.png")

        self.assertEqual([r.type.name for r in sent], ["IMAGE_URL"])
        self.assertEqual(self._written(), [])


if __name__ == "__main__":
    unittest.main()
