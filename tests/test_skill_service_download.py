# encoding:utf-8
"""Bounded-download guard for ``SkillService._download_file``.

Regression guard: before the size-capped downloader was wired in,
``_download_file`` buffered ``resp.content`` with no upper bound, so a hostile
or broken URL could fill disk with an unbounded response body. The downloader
now raises ``MediaTooLargeError`` on a Content-Length (or stream) over the cap.
"""
import os

import pytest
import requests
from common.media_download import MAX_FILE_BYTES, MediaTooLargeError
from unittest.mock import MagicMock, patch

from agent.skills.service import SkillService


def test_download_file_rejects_oversized_body(tmp_path):
    dest = str(tmp_path / "skill.zip")
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    # content is set only so the *old* code path (which wrote resp.content)
    # can complete without a TypeError; the size-capped downloader never reads
    # it because it aborts on the Content-Length pre-check first.
    resp.content = b""
    resp.headers = {"Content-Length": str(MAX_FILE_BYTES + 1)}
    resp.close.return_value = None

    # SkillService and common.media_download both import the same ``requests``
    # module, so patching its .get covers the call made by download_to_file.
    with patch.object(requests, "get", return_value=resp):
        with pytest.raises(MediaTooLargeError):
            SkillService._download_file("http://example.test/skill.zip", dest)

    # Nothing should have been written when the download is refused.
    assert not os.path.exists(dest)
