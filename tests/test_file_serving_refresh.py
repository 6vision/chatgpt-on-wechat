"""Mutable workspace outputs must be revalidated before a browser reuses them."""

from urllib.parse import urlencode

import pytest
import web

from channel.web.api import files


@pytest.fixture
def file_app(tmp_path, monkeypatch):
    output = tmp_path / "generated.txt"
    output.write_bytes(b"first version")
    monkeypatch.setattr(files, "_require_auth", lambda: None)
    monkeypatch.setattr(files, "_is_path_allowed", lambda path: path == str(output))
    return web.application(("/api/file", "FileServeHandler"), vars(files)), output


def test_mutable_file_requires_revalidation(file_app):
    app, output = file_app
    response = app.request("/api/file?" + urlencode({"path": str(output)}))
    assert response.status == "200 OK"
    assert response.data == b"first version"
    # This is a mutable path, not an immutable asset. Freshness must not permit
    # the cached response to hide the next generated version for an hour.
    assert "no-cache" in response.headers["Cache-Control"]


def test_repeated_url_reads_the_updated_output(file_app):
    app, output = file_app
    url = "/api/file?" + urlencode({"path": str(output), "v": "same-second"})
    first = app.request(url)
    output.write_bytes(b"second version")
    second = app.request(url)
    assert first.data == b"first version"
    assert second.data == b"second version"
    assert "no-cache" in first.headers["Cache-Control"]
    assert "no-cache" in second.headers["Cache-Control"]


def test_disallowed_path_is_still_refused(file_app, tmp_path):
    app, _ = file_app
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_bytes(b"not authorized")
    response = app.request("/api/file?" + urlencode({"path": str(unrelated)}))
    assert response.status == "404 Not Found"
    assert b"not authorized" not in response.data


def test_missing_file_is_still_refused(file_app):
    app, output = file_app
    output.unlink()
    response = app.request("/api/file?" + urlencode({"path": str(output)}))
    assert response.status == "404 Not Found"
