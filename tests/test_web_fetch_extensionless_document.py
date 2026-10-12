"""Extensionless downloads use the original, possibly single-use URL."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from threading import Thread

import pytest

from agent.tools.web_fetch.web_fetch import WebFetch


@pytest.mark.parametrize("path", ["/download?token=one-use", "/report.docx"])
def test_document_response_is_parsed_without_a_second_request(tmp_path, monkeypatch, path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("The quarterly revenue is 42 million.")
    buffer = BytesIO()
    document.save(buffer)
    payload = buffer.getvalue()
    requested = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append(self.path)
            if self.path != path or len(requested) > 1:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    # Local services are supported when the optional SSRF guard is disabled.
    # The HTTP server, request, download and python-docx parser all remain real.
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}{path}"
        result = WebFetch({"cwd": str(tmp_path)}).execute({"url": url})
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert result.status == "success", result.result
    assert "The quarterly revenue is 42 million." in result.result
    assert requested == [path]
    assert len(list((tmp_path / "tmp").iterdir())) == 1


@pytest.mark.parametrize("failure", ["http_error", "workspace_error"])
def test_acquired_stream_response_is_closed_on_early_failure(tmp_path, monkeypatch, failure):
    acquired = []
    cwd = tmp_path
    if failure == "workspace_error":
        cwd = tmp_path / "not-a-directory"
        cwd.write_text("occupied", encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404 if failure == "http_error" else 200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", "7")
            self.end_headers()
            self.wfile.write(b"payload")

        def log_message(self, *_args):
            pass

    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")
    tool = WebFetch({"cwd": str(cwd)})
    real_get = tool._safe_get

    def capture_response(*args, **kwargs):
        response = real_get(*args, **kwargs)
        acquired.append(response)
        return response

    # Observe real requests responses without replacing the HTTP operation.
    monkeypatch.setattr(tool, "_safe_get", capture_response)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/download"
        if failure == "http_error":
            result = tool.execute({"url": url})
            assert result.status == "error"
            assert "HTTP 404" in result.result
        else:
            with pytest.raises(NotADirectoryError):
                tool.execute({"url": url})
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert acquired
    assert all(response.raw.closed for response in acquired)
