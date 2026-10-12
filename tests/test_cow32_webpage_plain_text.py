from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

@contextmanager
def serve(body, content_type="text/plain; charset=utf-8", length=None, chunks=None, delay=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            if length is not None:
                self.send_header("Content-Length", str(length))
            self.end_headers()
            try:
                for chunk in (chunks if chunks is not None else [body]):
                    if delay:
                        import time
                        time.sleep(delay)
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

import pytest
from agent.tools.web_fetch.web_fetch import WebFetch

@pytest.mark.parametrize("content_type, body", [("text/plain; charset=utf-8", "  <item>value</item> &amp;\n  tail  "), ("application/json", '{"text": "<tag> &amp;"}')])
def test_native_extensionless_text_keeps_literal_content(tmp_path, monkeypatch, content_type, body):
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "0")
    with serve(body.encode(), content_type=content_type) as url:
        result = WebFetch({"cwd": str(tmp_path)}).execute({"url": url + "/content"})
    assert result.status == "success", result.result
    assert result.result.split("Content:\n", 1)[1] == body
