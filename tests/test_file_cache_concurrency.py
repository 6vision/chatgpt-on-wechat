"""Concurrent media callbacks must retain every first cached file."""

import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from Crypto.Cipher import AES

from channel.file_cache import FileCache


def test_concurrent_wecom_images_keep_both_first_files(monkeypatch, tmp_path):
    import channel.file_cache as cache_module
    import channel.wecom_bot.wecom_bot_message as message_module
    from channel.wecom_bot.wecom_bot_channel import WecomBotChannel

    cache = FileCache()
    monkeypatch.setattr(cache_module, "get_file_cache", lambda: cache)
    monkeypatch.setattr(message_module, "_get_tmp_dir", lambda: str(tmp_path))
    # Owned loopback media, using the same AES-CBC wire format the real parser reads.
    key = bytes(range(32))
    media = b"\x89PNG\r\n\x1a\nfixture-image"
    padding = 16 - len(media) % 16
    encrypted = AES.new(key, AES.MODE_CBC, key[:16]).encrypt(media + bytes([padding]) * padding)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(encrypted)))
            self.end_headers()
            self.wfile.write(encrypted)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    channel = WecomBotChannel.__wrapped__.__new__(WecomBotChannel.__wrapped__)
    first_read = threading.Event()
    another_read = threading.Event()
    release = threading.Event()
    read_lock = threading.Lock()
    original_get = cache.cache.get
    reads = 0
    errors = []

    def controlled_get(session_id):
        nonlocal reads
        value = original_get(session_id)
        with read_lock:
            reads += 1
            number = reads
        if number == 1:
            first_read.set()
            if not release.wait(3):
                raise AssertionError("first callback was not released")
        else:
            another_read.set()
        return value

    monkeypatch.setattr(cache.cache, "get", controlled_get)

    def receive(identifier):
        try:
            channel._build_context({
                "msgid": identifier, "msgtype": "image",
                "from": {"userid": "fixture-user"},
                "image": {
                    "url": "http://127.0.0.1:%s/image" % server.server_port,
                    "aeskey": base64.b64encode(key).decode(),
                },
            }, False)
        except BaseException as error:
            errors.append(error)

    first = threading.Thread(target=receive, args=("first",))
    second = threading.Thread(target=receive, args=("second",))
    try:
        first.start()
        assert first_read.wait(3)
        second.start()
        another_read.wait(0.2)
    finally:
        release.set()
        for thread in (first, second):
            if thread.ident is not None:
                thread.join(3)
        server.shutdown()
        server.server_close()
        server_thread.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    assert (tmp_path / "wecom_first.png").read_bytes() == media
    assert (tmp_path / "wecom_second.png").read_bytes() == media
    files = cache.get("fixture-user")
    assert {item["path"] for item in files} == {
        str(tmp_path / "wecom_first.png"), str(tmp_path / "wecom_second.png"),
    }


def test_duplicate_cached_file_remains_unique():
    cache = FileCache()
    cache.add("session", "fixture.png")
    cache.add("session", "fixture.png")
    assert cache.get("session") == [{"path": "fixture.png", "type": "image"}]


def test_clear_only_removes_selected_session():
    cache = FileCache()
    cache.add("first", "first.png")
    cache.add("second", "second.pdf", "file")
    cache.clear("first")
    assert cache.get("first") == []
    assert cache.get("second") == [{"path": "second.pdf", "type": "file"}]
