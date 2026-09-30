"""The edit and write tools must not destroy a file they failed to write.

Both tools used `open(path, 'w')`, which truncates the target to zero bytes the
moment the handle opens. A failure after that point - a full disk, an EIO, a
virus scanner holding a lock, the process being killed - left the user with a
half-written or empty file while the tool only reported that the edit had
failed. Neither tool asks for confirmation first, so that failure is the user's
problem, not the agent's.

common.atomic_write already solves this by writing a dot-prefixed sibling and
renaming it over the target, and every other store in the repo uses it. These
tests pin the two file tools to the same guarantee, and pin the happy path so a
later "fix" cannot pass by refusing to write at all.
"""

import builtins
import errno
import os

from agent.tools.edit.edit import Edit
from agent.tools.write.write import Write

ORIGINAL = "alpha\nbeta\ngamma\n"


def _write(path, text):
    """Write LF-only bytes; Path.write_text would translate to CRLF on Windows."""
    path.write_bytes(text.encode("utf-8"))
    return path


def _fail_writes_into(monkeypatch, folder):
    """Make any write of a file inside *folder* half land, then run out of space.

    The failure is injected at `f.write`, which both shapes of the tool call:
    the target itself when the tool opens it for truncation, and the sibling
    temp file once the tool writes atomically. So the tool genuinely hits ENOSPC
    either way and must report it - the only difference left between the two is
    whether the original file survives, which is the whole point.

    Not `os.replace`: atomic_write treats EBUSY/EXDEV/EACCES/EPERM from a rename
    as "this target can be written but not replaced" and falls back to truncating
    it in place, so a failure there would look like the bug it is meant to pin.
    """
    real_open = builtins.open
    wanted = os.path.normcase(os.path.abspath(str(folder)))

    class _OutOfSpace:
        """Delegates to a real file, except that the first write dies."""

        def __init__(self, handle):
            self._handle = handle

        def write(self, text):
            self._handle.write(text[: len(text) // 2])
            self._handle.flush()
            raise OSError(errno.ENOSPC, "No space left on device")

        def __enter__(self):
            self._handle.__enter__()
            return self

        def __exit__(self, *exc):
            return self._handle.__exit__(*exc)

        def __getattr__(self, name):
            return getattr(self._handle, name)

    def open_(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        here = os.path.dirname(os.path.abspath(os.fspath(file)))
        if "w" in mode and os.path.normcase(here) == wanted:
            return _OutOfSpace(handle)
        return handle

    monkeypatch.setattr(builtins, "open", open_)


def test_a_failed_edit_leaves_the_original_file_intact(tmp_path, monkeypatch):
    path = _write(tmp_path / "notes.md", ORIGINAL)
    _fail_writes_into(monkeypatch, tmp_path)

    result = Edit({"cwd": str(tmp_path)}).execute({
        "path": "notes.md", "oldText": "beta", "newText": "BETA",
    })

    assert result.status == "error", result.result
    assert "Error editing file" in str(result.result)
    assert path.read_text(encoding="utf-8") == ORIGINAL
    # No half-written sibling left behind for the user to trip over.
    assert [p.name for p in tmp_path.iterdir()] == ["notes.md"]


def test_a_failed_write_leaves_the_original_file_intact(tmp_path, monkeypatch):
    path = _write(tmp_path / "notes.md", ORIGINAL)
    _fail_writes_into(monkeypatch, tmp_path)

    result = Write({"cwd": str(tmp_path)}).execute({
        "path": "notes.md", "content": "replacement\n",
    })

    assert result.status == "error", result.result
    assert "Error writing file" in str(result.result)
    assert path.read_text(encoding="utf-8") == ORIGINAL
    assert [p.name for p in tmp_path.iterdir()] == ["notes.md"]


def test_a_failed_write_to_a_new_file_creates_nothing(tmp_path, monkeypatch):
    _fail_writes_into(monkeypatch, tmp_path)

    result = Write({"cwd": str(tmp_path)}).execute({
        "path": "fresh.md", "content": "hello\n",
    })

    assert result.status == "error", result.result
    assert list(tmp_path.iterdir()) == []


def test_a_successful_edit_still_writes_and_reports_a_diff(tmp_path):
    path = _write(tmp_path / "notes.md", ORIGINAL)

    result = Edit({"cwd": str(tmp_path)}).execute({
        "path": "notes.md", "oldText": "beta", "newText": "BETA",
    })

    assert result.status == "success", result.result
    assert path.read_text(encoding="utf-8") == "alpha\nBETA\ngamma\n"
    assert result.result["path"] == "notes.md"
    assert "BETA" in result.result["diff"]


def test_a_successful_write_still_writes_and_reports_the_byte_count(tmp_path):
    path = _write(tmp_path / "notes.md", ORIGINAL)
    content = "unicode: 新\nline two\n"

    result = Write({"cwd": str(tmp_path)}).execute({
        "path": "notes.md", "content": content,
    })

    assert result.status == "success", result.result
    assert path.read_text(encoding="utf-8") == content
    assert result.result["bytes_written"] == len(content.encode("utf-8"))
    assert [p.name for p in tmp_path.iterdir()] == ["notes.md"]
