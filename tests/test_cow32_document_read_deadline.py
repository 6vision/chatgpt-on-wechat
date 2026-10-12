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

from agent.tools.web_fetch import web_fetch as module

def test_native_trickling_document_exceeds_whole_transfer_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "0")
    monkeypatch.setattr(module, "PAGE_READ_SECONDS", 0.1)
    with serve(b"", chunks=[b"a" * 65536 for _ in range(4)], delay=0.06) as url:
        result = module.WebFetch({"cwd": str(tmp_path)}).execute({"url": url + "/report.txt"})
    assert result.status == "error", result.result
    assert "timed out" in result.result
    assert not list((tmp_path / "tmp").iterdir())

def test_native_complete_document_remains_readable(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "0")
    with serve(b"complete text") as url:
        result = module.WebFetch({"cwd": str(tmp_path)}).execute({"url": url + "/report.txt"})
    assert result.status == "success", result.result
    assert "complete text" in result.result
