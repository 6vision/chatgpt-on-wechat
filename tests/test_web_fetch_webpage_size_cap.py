# encoding:utf-8
"""A web page response must be bounded by the same size limit as a document.

``WebFetch._fetch_document`` refuses anything over ``MAX_FILE_SIZE``, checking
the ``Content-Length`` header and every streamed chunk. ``_fetch_webpage`` used
to check neither: it called ``_safe_get(url, stream=True)`` and then read
``response.text``, which joins ``iter_content`` and therefore buffers the entire
body before returning. ``stream=True`` does not prevent that, and requests'
``timeout`` is a per-read *inactivity* timeout, so a peer that keeps sending one
byte at a time is never cut off and the buffer grows without bound.

Both paths are exercised here. The stubbed cases pin the exact behaviour (the
body must not be read at all when ``Content-Length`` already declares it too
large, and a headless stream must stop near the cap instead of draining), and
the socket cases confirm the same cap over a real HTTP server that sends no
``Content-Length`` at all.

``MAX_FILE_SIZE`` is lowered so the oversized cases stay fast and small; the
value the check consults is the module constant either way, and every
assertion formats its expectation through ``format_size`` so it tracks whatever
that constant is set to.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from agent.tools.web_fetch import web_fetch as web_fetch_module
from agent.tools.web_fetch.web_fetch import WebFetch
from agent.tools.utils.truncate import format_size


SMALL_LIMIT = 4096
SMALL_PAGE = (
    b"<html><head><title>Quarterly report</title></head>"
    b"<body><p>Revenue is 42 million.</p></body></html>"
)


class StreamingResponse:
    """Stand-in for a streamed response that buffers the way requests does.

    ``requests.Response.text`` is a property that first joins ``iter_content``,
    so the whole body is read before any text can be returned. Reproducing that
    is the point of this stand-in: ``bytes_read`` records how much of the stream
    the tool actually pulled, which is what distinguishes "refused the page"
    from "refused it only after downloading all of it".
    """

    def __init__(self, chunks, content_length=None,
                 content_type="text/html; charset=utf-8"):
        self._chunks = list(chunks)
        self._content = False
        self._content_consumed = False
        self.encoding = None
        self.status_code = 200
        self.closed = False
        self.bytes_read = 0
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    @property
    def total_bytes(self):
        return sum(len(chunk) for chunk in self._chunks)

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        for chunk in self._chunks:
            self.bytes_read += len(chunk)
            yield chunk
        self._content_consumed = True

    @property
    def content(self):
        if self._content is False:
            self._content = b"".join(self.iter_content(10240))
        self._content_consumed = True
        return self._content

    @property
    def apparent_encoding(self):
        return "utf-8"

    @property
    def text(self):
        if not self.content:
            return ""
        return self.content.decode(self.encoding or self.apparent_encoding,
                                   errors="replace")

    def close(self):
        self.closed = True


@pytest.fixture
def serve(monkeypatch):
    """Replace the tool's safe_get seam with a canned response."""
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")

    def install(response):
        calls = []

        def get(url, **kwargs):
            calls.append(dict(kwargs, url=url))
            return response

        monkeypatch.setattr(web_fetch_module, "safe_get", get)
        return calls

    return install


@pytest.fixture
def small_limit(monkeypatch):
    """Shrink the cap so the oversized cases stay quick and cheap to build."""
    monkeypatch.setattr(web_fetch_module, "MAX_FILE_SIZE", SMALL_LIMIT)


def _headless_page(chunks=40, chunk_size=1024):
    """A page big enough to trip the cap, chunked and without a Content-Length."""
    chunk = b"<p>" + b"a" * (chunk_size - 7) + b"</p>"
    return StreamingResponse([chunk] * chunks, content_length=None)


def _start_server(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join()


def test_declared_oversize_page_is_refused_without_reading_the_body(serve, small_limit):
    """A Content-Length over the cap is rejected before a byte is read."""
    response = StreamingResponse([SMALL_PAGE],
                                 content_length=512 * 1024 * 1024)
    serve(response)
    tool = WebFetch(config={"cwd": "."})

    result = tool.execute({"url": "https://example.com/page"})

    assert result.status == "error"
    assert format_size(512 * 1024 * 1024) in result.result
    assert format_size(SMALL_LIMIT) in result.result
    assert response.bytes_read == 0


def test_headless_page_over_the_cap_stops_reading_and_is_refused(serve, small_limit):
    """A stream with no Content-Length is cut off near the cap, not drained."""
    response = _headless_page()
    total = response.total_bytes
    serve(response)
    tool = WebFetch(config={"cwd": "."})

    result = tool.execute({"url": "https://example.com/page"})

    assert result.status == "error"
    assert format_size(SMALL_LIMIT) in result.result
    # At most the cap plus the one chunk that crossed it, and far short of the
    # whole body: the point of the cap is that the rest is never buffered.
    assert response.bytes_read <= SMALL_LIMIT + 1024
    assert response.bytes_read < total
    assert response.closed


def test_page_within_the_cap_is_still_extracted(serve, small_limit):
    """An ordinary page is unaffected by the cap."""
    serve(StreamingResponse([SMALL_PAGE[:40], SMALL_PAGE[40:]],
                            content_length=len(SMALL_PAGE)))
    tool = WebFetch(config={"cwd": "."})

    result = tool.execute({"url": "https://example.com/page"})

    assert result.status == "success", result.result
    assert "Quarterly report" in result.result
    assert "Revenue is 42 million." in result.result


def test_page_under_cap_without_content_length_is_extracted(serve, small_limit):
    """A chunked page with no Content-Length still succeeds when it fits."""
    serve(_headless_page(chunks=2))
    tool = WebFetch(config={"cwd": "."})

    result = tool.execute({"url": "https://example.com/page"})

    assert result.status == "success", result.result


def test_real_headless_page_over_the_cap_is_refused(monkeypatch, small_limit):
    """Over a real socket, a page with no Content-Length is capped too."""
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")
    chunk = b"<p>" + b"a" * 1017 + b"</p>"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            for _ in range(40):
                try:
                    self.wfile.write(chunk)
                except OSError:
                    break

        def log_message(self, *_args):
            pass

    server, thread = _start_server(Handler)
    try:
        url = f"http://127.0.0.1:{server.server_port}/page"
        result = WebFetch(config={"cwd": "."}).execute({"url": url})
    finally:
        _stop_server(server, thread)

    assert result.status == "error"
    assert format_size(SMALL_LIMIT) in result.result


def test_real_page_under_the_cap_is_extracted(monkeypatch, small_limit):
    """A small real page still round-trips through the capped path."""
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(SMALL_PAGE)))
            self.end_headers()
            self.wfile.write(SMALL_PAGE)

        def log_message(self, *_args):
            pass

    server, thread = _start_server(Handler)
    try:
        url = f"http://127.0.0.1:{server.server_port}/page"
        result = WebFetch(config={"cwd": "."}).execute({"url": url})
    finally:
        _stop_server(server, thread)

    assert result.status == "success", result.result
    assert "Revenue is 42 million." in result.result