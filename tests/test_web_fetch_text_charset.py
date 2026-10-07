"""Declared text-download encodings survive the real HTTP/download pipeline."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from agent.tools.web_fetch.web_fetch import WebFetch


@pytest.mark.parametrize(
    "suffix, encoding, charset",
    [
        (".txt", "windows-1252", "windows-1252"),
        (".csv", "utf-8", "utf-8"),
        (".md", "utf-8", None),
        (".log", "utf-8", "not-a-real-codec"),
        (".tsv", "utf-16", "utf-16"),
    ],
)
def test_downloaded_text_uses_declared_charset_or_existing_fallback(
    tmp_path, monkeypatch, suffix, encoding, charset
):
    text = "Quarterly café costs €42 — paid."
    payload = text.encode(encoding)
    path = "/report" + suffix
    requested = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append(self.path)
            self.send_response(200)
            content_type = "text/plain"
            if charset:
                content_type += "; charset=" + charset
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    # The documented optional guard permits owned local services; the HTTP
    # request, file download, codec and text parser remain real.
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = WebFetch({"cwd": str(tmp_path)}).execute(
            {"url": f"http://127.0.0.1:{server.server_port}{path}"}
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert result.status == "success", result.result
    assert text in result.result
    assert requested == [path]
    saved_files = list((tmp_path / "tmp").iterdir())
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == payload
