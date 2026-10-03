# encoding:utf-8
"""AssetsHandler only serves files that resolve inside static/, not prefix-sharing siblings."""

import os
import sys
import types
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import web

from channel.web.api import pages as pages_api


class _NotFound(web.HTTPError):
    def __init__(self):
        Exception.__init__(self, "404 Not Found")


def _raise_notfound(*args, **kwargs):
    raise _NotFound()


@pytest.fixture
def get(tmp_path):
    web_dir = tmp_path / "channel" / "web"
    (web_dir / "api").mkdir(parents=True)
    (web_dir / "static").mkdir()
    (web_dir / "static" / "console.css").write_bytes(b"in-tree")
    (web_dir / "static_backup").mkdir()
    (web_dir / "static_backup" / "secret.txt").write_bytes(b"SECRET")
    if os.name != "nt":
        os.symlink(web_dir / "static_backup" / "secret.txt", web_dir / "static" / "link.css")

    def _get(file_path):
        with patch.object(pages_api, "__file__", str(web_dir / "api" / "pages.py")), \
                patch.object(pages_api.web, "header", lambda *a, **k: None), \
                patch.object(pages_api.web, "ctx", types.SimpleNamespace(get=lambda *a, **k: {})), \
                patch.object(pages_api.web, "notfound", _raise_notfound):
            return pages_api.AssetsHandler().GET(file_path)
    return _get


@pytest.mark.parametrize("path", [
    os.path.join("..", "static_backup", "secret.txt"),
    pytest.param("link.css", marks=pytest.mark.skipif(os.name == "nt", reason="symlinks")),
])
def test_escape_is_refused(get, path):
    with pytest.raises(_NotFound):
        get(path)


def test_file_in_static_is_served(get):
    assert get("console.css") == b"in-tree"
