"""A document download that dies mid-stream must not leave a partial file.

``WebFetch._fetch_document`` streams a remote document into ``<cwd>/tmp`` and
only keeps it when the whole transfer completed. A ``ReadTimeout`` /
``ConnectionError`` raised while the body is being read lands *after*
``local_path`` has been opened for writing, so the truncated file must be
removed on that path too. Leaving it behind lets a later content-type guess or
retry pick up a corrupt file out of the tmp directory the app sweeps.

No real network is used: the ``safe_get`` seam is stubbed throughout.
"""

import pytest
import requests

from agent.tools.web_fetch import web_fetch as web_fetch_module
from agent.tools.web_fetch.web_fetch import WebFetch


class Response:
    """Stand-in for a streaming response whose body may die part-way through."""

    def __init__(self, chunks=(b"chunk",), failure=None, status_code=200):
        self.chunks = chunks
        self.failure = failure
        self.status_code = status_code
        self.headers = {"Content-Length": str(sum(len(c) for c in chunks))}
        self.iterated = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        self.iterated = True
        yield from self.chunks
        if self.failure is not None:
            raise self.failure

    def close(self):
        pass


@pytest.fixture
def serve(monkeypatch):
    """Replace the tool's safe_get seam with a canned response."""

    def install(response):
        calls = []

        def get(url, **kwargs):
            calls.append(dict(kwargs, url=url))
            return response

        monkeypatch.setattr(web_fetch_module, "safe_get", get)
        return calls

    return install


@pytest.mark.parametrize("failure", [
    requests.ConnectionError("connection reset by peer"),
    requests.Timeout("timed out"),
    requests.ReadTimeout("read timed out"),
], ids=["connection-error", "timeout", "read-timeout"])
def test_transfer_dying_mid_stream_leaves_no_partial_file(tmp_path, serve, failure):
    """A stream that dies after one chunk reports failure and leaves tmp empty."""
    serve(Response(chunks=[b"partial-bytes"], failure=failure))
    tool = WebFetch(config={"cwd": str(tmp_path)})

    result = tool.execute({"url": "https://example.com/report.pdf"})

    assert result.status == "error"
    tmp_dir = tmp_path / "tmp"
    assert tmp_dir.is_dir()
    assert list(tmp_dir.iterdir()) == []


def test_mid_transfer_failure_does_not_claim_it_failed_to_connect(tmp_path, serve):
    """The connection succeeded, so the message must not say it failed."""
    serve(Response(chunks=[b"partial-bytes"], failure=requests.ConnectionError("reset")))
    tool = WebFetch(config={"cwd": str(tmp_path)})

    result = tool.execute({"url": "https://example.com/report.pdf"})

    assert "Failed to connect" not in result.result
    assert "example.com" in result.result


def test_successful_download_keeps_the_file(tmp_path, serve):
    """A transfer that completes keeps the file for the parser to read."""
    serve(Response(chunks=[b"hello ", b"world"]))
    tool = WebFetch(config={"cwd": str(tmp_path)})

    result = tool.execute({"url": "https://example.com/notes.txt"})

    assert result.status == "success"
    saved = list((tmp_path / "tmp").iterdir())
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"hello world"
    assert "hello world" in result.result
