"""Local QQ uploads past the 5MB gateway cap go through the chunked API."""

from types import SimpleNamespace

from channel.qq import qq_channel


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}
        self.text = str(self._body)

    def json(self):
        return self._body


def _channel(monkeypatch):
    cls = qq_channel.QQChannel.__wrapped__
    channel = cls.__new__(cls)
    monkeypatch.setattr(channel, "_get_auth_headers", lambda: {}, raising=False)
    return channel


def _msg():
    return SimpleNamespace(_rawmsg={"group_openid": "g1"}, from_user_id="u1")


def test_large_file_runs_prepare_parts_and_merge(monkeypatch, tmp_path):
    monkeypatch.setattr(qq_channel, "QQ_BINARY_UPLOAD_LIMIT", 4)
    path = tmp_path / "big.bin"
    path.write_bytes(b"abcdefghij")
    calls = []

    def post(url, json=None, **_):
        calls.append((url.rsplit("/", 1)[-1], json))
        if url.endswith("/upload_prepare"):
            return _Resp(body={"upload_id": "up1", "block_size": 6, "parts": [
                {"index": 2, "presigned_url": "https://put/2"},
                {"index": 1, "presigned_url": "https://put/1"},
            ]})
        if url.endswith("/files"):
            return _Resp(body={"file_info": "FI"})
        return _Resp()

    puts = []
    monkeypatch.setattr(qq_channel.requests, "post", post)
    monkeypatch.setattr(qq_channel.requests, "put",
                        lambda url, data=None, **_: puts.append((url, data)) or _Resp())

    channel = _channel(monkeypatch)
    info = channel._upload_local_file(str(path), qq_channel.QQ_FILE_TYPE_FILE, _msg(),
                                      "GROUP_AT_MESSAGE_CREATE")

    assert info == "FI"
    assert puts == [("https://put/1", b"abcdef"), ("https://put/2", b"ghij")]
    assert [name for name, _ in calls] == ["upload_prepare", "upload_part_finish",
                                           "upload_part_finish", "files"]
    assert calls[-1][1]["upload_id"] == "up1"


def test_small_file_keeps_the_base64_path(monkeypatch, tmp_path):
    path = tmp_path / "small.txt"
    path.write_bytes(b"hi")
    channel = _channel(monkeypatch)
    monkeypatch.setattr(channel, "_upload_rich_media_base64", lambda *a, **k: "B64")
    monkeypatch.setattr(channel, "_upload_rich_media_chunked", lambda *a, **k: "CHUNKED")
    assert channel._upload_local_file(str(path), 4, _msg(), "GROUP_AT_MESSAGE_CREATE") == "B64"


def test_file_over_the_hard_limit_is_refused_with_a_notice(monkeypatch, tmp_path):
    monkeypatch.setattr(qq_channel, "QQ_HARD_LIMIT_BYTES", 1)
    path = tmp_path / "huge.bin"
    path.write_bytes(b"xx")
    channel = _channel(monkeypatch)
    sent = []
    monkeypatch.setattr(channel, "_send_text", lambda text, *a: sent.append(text))
    assert channel._reject_oversized_local_file(str(path), _msg(), "GROUP_AT_MESSAGE_CREATE", "m1")
    assert sent and "too large" in sent[0]
