"""The log views must not read a whole log file to show its last few lines.

``run.log`` is appended to for as long as CowAgent runs and is never rotated, so
it only grows. Three places replayed a tail with ``readlines()`` and then sliced
the result:

* the web logs view (last 200 lines),
* the chat ``cow logs`` command (up to 50) -- and this one runs inside the bot
  process, so a long-lived instance gets OOM-killed by its own help command,
* ``cow logs`` on the CLI (50).

Every line ever written was loaded into memory to display a handful of them.
They now all share ``common.utils.tail_lines``, which walks the file backwards
in fixed-size blocks and stops once enough lines have been found.
"""

import builtins
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import plugins
from channel.web.api import logs as logs_mod
from cli.commands.process import _print_last_lines
from common.utils import tail_lines


_old_plugin_path = plugins.instance.current_plugin_path
plugins.instance.current_plugin_path = os.path.join(os.getcwd(), "plugins", "cow_cli")
try:
    from plugins.cow_cli import cow_cli  # noqa: F401 - loads the plugin module

    CowCliPlugin = plugins.instance.plugins["COW_CLI"]
finally:
    plugins.instance.current_plugin_path = _old_plugin_path


class _RecordingFile:
    """Wraps a file object and counts how much of it the caller actually reads."""

    def __init__(self, inner, record):
        self._inner = inner
        self._record = record

    def readlines(self, *args, **kwargs):
        self._record["readlines"] += 1
        return self._inner.readlines(*args, **kwargs)

    def read(self, *args, **kwargs):
        data = self._inner.read(*args, **kwargs)
        self._record["read_bytes"] += len(data)
        return data

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __enter__(self):
        self._inner.__enter__()
        return self

    def __exit__(self, *exc):
        return self._inner.__exit__(*exc)


def _write_log(path, line_count):
    # newline="\n" keeps the fixture byte-identical on Windows, where the
    # default translation would write CRLF and change what "a line" means.
    with builtins.open(str(path), "w", encoding="utf-8", newline="\n") as f:
        for i in range(line_count):
            f.write(f"[INFO] 2026-09-30 00:00:00 - log line number {i}\n")
    return path


def _spy_on_reads(monkeypatch):
    """Count the bytes ``tail_lines`` reads, wherever it is called from."""
    record = {"readlines": 0, "read_bytes": 0}
    real_open = builtins.open

    def spy_open(file, *args, **kwargs):
        return _RecordingFile(real_open(file, *args, **kwargs), record)

    # "open" is a builtin the module never imports, so it has no attribute yet.
    monkeypatch.setattr("common.utils.open", spy_open, raising=False)
    return record


# ── the shared helper ────────────────────────────────────────────────


def test_tail_lines_returns_the_last_n_lines(tmp_path):
    path = _write_log(tmp_path / "run.log", 5000)
    with builtins.open(str(path), "r", encoding="utf-8") as f:
        expected = f.readlines()[-200:]

    assert tail_lines(str(path), 200) == expected


def test_tail_lines_reads_only_the_tail(tmp_path, monkeypatch):
    path = _write_log(tmp_path / "run.log", 20000)
    record = _spy_on_reads(monkeypatch)

    tail = tail_lines(str(path), 200)

    assert len(tail) == 200
    assert record["readlines"] == 0, (
        "the whole log was read into memory just to keep the last 200 lines"
    )
    assert record["read_bytes"] < path.stat().st_size // 2, (
        f"read {record['read_bytes']} bytes of a {path.stat().st_size} byte log"
    )


def test_tail_lines_handles_a_file_shorter_than_the_limit(tmp_path):
    path = _write_log(tmp_path / "run.log", 3)

    tail = tail_lines(str(path), 200)

    assert len(tail) == 3
    assert tail[-1].endswith("log line number 2\n")


def test_tail_lines_handles_an_empty_file(tmp_path):
    path = tmp_path / "run.log"
    path.write_bytes(b"")

    assert tail_lines(str(path), 200) == []


def test_tail_lines_returns_nothing_for_a_non_positive_limit(tmp_path):
    path = _write_log(tmp_path / "run.log", 10)

    assert tail_lines(str(path), 0) == []
    assert tail_lines(str(path), -1) == []


def test_tail_lines_keeps_the_line_endings_so_callers_can_join_them(tmp_path):
    path = _write_log(tmp_path / "run.log", 4)

    joined = "".join(tail_lines(str(path), 2))

    assert joined.count("\n") == 2, "the newlines must survive so callers can join"
    assert joined.splitlines() == [
        "[INFO] 2026-09-30 00:00:00 - log line number 2",
        "[INFO] 2026-09-30 00:00:00 - log line number 3",
    ]


# ── the three callers ────────────────────────────────────────────────


def _handler_env(tmp_path, monkeypatch):
    """Point the logs handler at *tmp_path* and stub out the request plumbing."""
    monkeypatch.setattr(logs_mod, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(logs_mod, "_require_auth", lambda: None)
    monkeypatch.setattr(logs_mod.web, "header", lambda *a, **k: None)


def test_the_web_logs_view_replays_the_tail_without_readlines(tmp_path, monkeypatch):
    path = _write_log(tmp_path / "run.log", 20000)
    record = _spy_on_reads(monkeypatch)
    _handler_env(tmp_path, monkeypatch)

    first_chunk = next(logs_mod.LogsHandler().GET())

    assert b'"type": "init"' in first_chunk
    assert b"log line number 19999" in first_chunk
    assert record["readlines"] == 0
    assert record["read_bytes"] < path.stat().st_size // 2


def test_the_chat_logs_command_reads_only_the_tail(tmp_path, monkeypatch):
    path = _write_log(tmp_path / "run.log", 20000)
    record = _spy_on_reads(monkeypatch)
    monkeypatch.setattr(CowCliPlugin, "_find_log_file", lambda self: str(path))
    plugin = CowCliPlugin.__new__(CowCliPlugin)

    out = plugin._cmd_logs("20", None)

    assert "log line number 19999" in out
    assert record["readlines"] == 0
    assert record["read_bytes"] < path.stat().st_size // 2


def test_the_cli_logs_command_prints_only_the_tail(tmp_path, monkeypatch, capsys):
    path = _write_log(tmp_path / "run.log", 20000)
    record = _spy_on_reads(monkeypatch)

    _print_last_lines(str(path), 5)

    printed = capsys.readouterr().out
    assert "log line number 19999" in printed
    assert "log line number 19990" not in printed
    assert len(printed.splitlines()) == 5
    assert record["readlines"] == 0
    assert record["read_bytes"] < path.stat().st_size // 2
