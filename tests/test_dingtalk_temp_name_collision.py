# encoding:utf-8
"""DingTalk images fetched over plain HTTP must not share one temp filename.

The ``dingtalk://download/...`` branch already discriminates: it prefixes an
md5 of the download code (``_media_filename``). The plain HTTP branch derived
the name purely from the remote basename, with no per-message component::

    dest_name = safe_filename(file_name or image_url.split("/")[-1].split("?")[0])

Every message lands in the same agent-managed ``tmp_dir``
(``state_dir.tmp_dir()``), so two people in one group who each send a file
called ``photo.jpg`` resolve to the very same ``<tmp>/photo.jpg``.
``save_response`` finishes with ``os.replace(temp_path, path)``, so the second
download does not fail loudly -- it atomically overwrites the first file.

The agent is then handed two messages pointing at one path, so it reads whichever
image landed last and the other user's picture is gone. Remote names are not
unique; the signed download URL is what identifies the message, so the fix
hashes the URL the same way the sibling branch hashes its download code.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.dingtalk import dingtalk_message
from channel.dingtalk.dingtalk_message import download_image_file

ALICE_URL = "https://cdn.example/alice/photo.jpg"
BOB_URL = "https://cdn.example/bob/photo.jpg"

PAYLOADS = {ALICE_URL: b"alice-image-bytes", BOB_URL: b"bob-image-bytes"}


class _FakeResponse:
    """The subset of a streamed ``requests`` response the downloader uses."""

    def __init__(self, body):
        self._body = body
        self.headers = {"Content-Length": str(len(body))}
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=None):
        step = chunk_size or len(self._body) or 1
        for start in range(0, len(self._body), step):
            yield self._body[start:start + step]

    def close(self):
        self.closed = True


class _FakeRequests:
    """Serves each URL its own bytes, so an overwrite is visible in the file."""

    def get(self, url, **kwargs):
        return _FakeResponse(PAYLOADS.get(url, b"unexpected-url"))


class DingtalkTempFilenameCollisionTest(unittest.TestCase):
    """Two same-named remote images must not resolve to one temp path."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dingtalk-collision-")
        self._real_requests = dingtalk_message.download_to_file.__globals__["requests"]
        dingtalk_message.download_to_file.__globals__["requests"] = _FakeRequests()

    def tearDown(self):
        dingtalk_message.download_to_file.__globals__["requests"] = self._real_requests
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _download(self, url):
        return download_image_file(url, self.temp_dir)

    def test_same_remote_name_downloads_to_different_paths(self):
        alice = self._download(ALICE_URL)
        bob = self._download(BOB_URL)

        self.assertTrue(alice and os.path.isfile(alice), "alice's image should download")
        self.assertTrue(bob and os.path.isfile(bob), "bob's image should download")
        self.assertNotEqual(
            alice, bob,
            "both messages name photo.jpg, so an undiscriminated temp path makes "
            "the second download clobber the first user's image",
        )

    def test_both_images_survive_on_disk(self):
        alice = self._download(ALICE_URL)
        bob = self._download(BOB_URL)

        with open(alice, "rb") as handle:
            alice_bytes = handle.read()
        with open(bob, "rb") as handle:
            bob_bytes = handle.read()

        self.assertEqual(b"alice-image-bytes", alice_bytes, "alice's image was overwritten")
        self.assertEqual(b"bob-image-bytes", bob_bytes, "bob's image is wrong")

    def test_the_remote_name_is_still_readable_in_the_path(self):
        """Uniqueness must not cost the agent a readable basename."""
        alice = self._download(ALICE_URL)

        self.assertIn("photo.jpg", os.path.basename(alice))

    def test_a_signed_query_string_stays_out_of_the_path(self):
        """The pre-existing guarantee: no token may leak into a filename."""
        url = "https://cdn.example/dir/photo.jpg?token=secret"
        PAYLOADS[url] = b"signed"
        try:
            path = self._download(url)
        finally:
            PAYLOADS.pop(url, None)

        self.assertNotIn("secret", os.path.basename(path))

    def test_distinct_basenames_still_get_distinct_files(self):
        first = self._download(ALICE_URL)
        other_url = "https://cdn.example/bob/other.jpg"
        PAYLOADS[other_url] = b"other"
        try:
            second = self._download(other_url)
        finally:
            PAYLOADS.pop(other_url, None)

        self.assertNotEqual(first, second)
        self.assertEqual(2, len(os.listdir(self.temp_dir)))


if __name__ == "__main__":
    unittest.main()
