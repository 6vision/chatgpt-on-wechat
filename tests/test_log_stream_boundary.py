"""Log replay must hand off to the live stream without losing appended lines."""

import json

from channel.web.api import logs
from common.utils import tail_lines


def test_live_stream_keeps_lines_appended_after_init(tmp_path, monkeypatch):
    path = tmp_path / "run.log"
    path.write_text("initial\n", encoding="utf-8")
    monkeypatch.setattr(logs, "_require_auth", lambda: None)
    monkeypatch.setattr(logs, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(logs.web, "header", lambda *args: None)
    stream = logs.LogsHandler().GET()
    try:
        initial = json.loads(next(stream).decode()[6:])
        assert initial == {"type": "init", "content": "initial\n"}
        with path.open("a", encoding="utf-8") as handle:
            handle.write("arrived-after-init\n")
        following = next(stream)
        assert following.startswith(b"data: ")
        assert json.loads(following.decode()[6:]) == {
            "type": "line", "content": "arrived-after-init\n",
        }
        assert next(stream) == b": keepalive\n\n"
    finally:
        stream.close()


def test_tail_snapshot_excludes_later_append(tmp_path):
    path = tmp_path / "run.log"
    path.write_text("older\ninitial\n", encoding="utf-8")
    boundary = path.stat().st_size
    with path.open("a", encoding="utf-8") as handle:
        handle.write("later\n")
    assert tail_lines(path, 1, end_offset=boundary) == ["initial\n"]
    assert tail_lines(path, 1) == ["later\n"]


def test_live_stream_idle_control(tmp_path, monkeypatch):
    path = tmp_path / "run.log"
    path.write_text("initial\n", encoding="utf-8")
    monkeypatch.setattr(logs, "_require_auth", lambda: None)
    monkeypatch.setattr(logs, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(logs.web, "header", lambda *args: None)
    stream = logs.LogsHandler().GET()
    try:
        assert json.loads(next(stream).decode()[6:]) == {"type": "init", "content": "initial\n"}
        assert next(stream) == b": keepalive\n\n"
    finally:
        stream.close()


def test_live_stream_utf8_initial_control(tmp_path, monkeypatch):
    path = tmp_path / "run.log"
    content = "先前 café 🚀\n"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(logs, "_require_auth", lambda: None)
    monkeypatch.setattr(logs, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(logs.web, "header", lambda *args: None)
    stream = logs.LogsHandler().GET()
    try:
        assert json.loads(next(stream).decode()[6:]) == {"type": "init", "content": content}
        assert next(stream) == b": keepalive\n\n"
    finally:
        stream.close()


def test_live_stream_initial_read_error_control(tmp_path, monkeypatch):
    import builtins

    path = tmp_path / "run.log"
    path.write_text("initial\n", encoding="utf-8")
    monkeypatch.setattr(logs, "_require_auth", lambda: None)
    monkeypatch.setattr(logs, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(logs.web, "header", lambda *args: None)
    original_open = builtins.open

    def denied_open(target, *args, **kwargs):
        if str(target) == str(path):
            raise PermissionError("fixture unreadable")
        return original_open(target, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", denied_open)
    stream = logs.LogsHandler().GET()
    try:
        assert json.loads(next(stream).decode()[6:]) == {
            "type": "error", "message": "fixture unreadable",
        }
    finally:
        stream.close()
