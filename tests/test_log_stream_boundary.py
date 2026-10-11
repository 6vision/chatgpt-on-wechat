"""Log replay must hand off to the live tail without losing appended lines."""

import json

import pytest

from channel.web.api import logs
from common.utils import tail_lines


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "_require_auth", lambda: None)
    monkeypatch.setattr(logs, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(logs.web, "header", lambda *args: None)
    path = tmp_path / "run.log"
    path.write_text("先前 café\n", encoding="utf-8")
    return path


def _event(chunk):
    return json.loads(chunk.decode()[6:])


def test_line_appended_after_init_reaches_the_live_tail(log_path):
    stream = logs.LogsHandler().GET()
    try:
        assert _event(next(stream)) == {"type": "init", "content": "先前 café\n"}
        with log_path.open("a", encoding="utf-8") as f:
            f.write("arrived-after-init\n")
        assert _event(next(stream)) == {"type": "line", "content": "arrived-after-init\n"}
        assert next(stream) == b": keepalive\n\n"
    finally:
        stream.close()


def test_tail_lines_stops_at_the_captured_offset(tmp_path):
    path = tmp_path / "run.log"
    path.write_text("older\ninitial\n", encoding="utf-8")
    boundary = path.stat().st_size
    with path.open("a", encoding="utf-8") as f:
        f.write("later\n")
    assert tail_lines(path, 1, end_offset=boundary) == ["initial\n"]
    assert tail_lines(path, 1) == ["later\n"]
