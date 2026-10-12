# encoding:utf-8
"""Same-named DingTalk HTTP images get distinct temp paths keyed by the signed URL."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.dingtalk import dingtalk_message


def test_same_remote_name_downloads_to_different_paths(tmp_path):
    download = dingtalk_message.download_image_file
    with patch.object(dingtalk_message, "download_to_file"):
        alice = download("https://cdn.example/alice/photo.jpg?token=secret", str(tmp_path))
        bob = download("https://cdn.example/bob/photo.jpg", str(tmp_path))

    assert alice != bob
    assert "photo.jpg" in os.path.basename(alice)
    assert "secret" not in os.path.basename(alice)
