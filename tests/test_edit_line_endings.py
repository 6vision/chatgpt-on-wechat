# encoding:utf-8
"""
Regression tests for the Edit tool's line-ending preservation.

The Edit tool read the target in universal-newline mode (newline=None), so
every CRLF had already been translated to LF by the time it called
detect_line_ending() to ask what the file actually used. The answer was
therefore always '\n', restore_line_endings() was a no-op, and the text-mode
write then rewrote every '\n' as os.linesep. On Windows that meant editing one
line of an LF file rewrote the *whole* file to CRLF: `#!/bin/sh\r` is not a
valid shebang, every untouched line shows as modified in the diff and in
version control, and the returned diff mentions only the intended line, so
nothing signalled it.

The real ending has to come from the file's bytes, which is what
agent/workspace/service.py already does. Mixed files follow detect_line_ending()'s
own rule: CRLF present anywhere wins, so the file is normalised to CRLF rather
than guessed line by line.

Every assertion here is made on bytes. Reading the file back in text mode
would translate CRLF to LF and make each of these tests pass vacuously, for
exactly the reason the tool was broken.
"""
from agent.tools.edit.edit import Edit


def _edit(tmp_path, name, data, old_text, new_text):
    """Write exact bytes, run a one-line edit, and return (path, result)."""
    target = tmp_path / name
    # A text-mode write would translate these bytes on Windows, which is the
    # very translation under test.
    target.write_bytes(data)
    result = Edit({"cwd": str(tmp_path)}).execute({
        "path": str(target),
        "oldText": old_text,
        "newText": new_text,
    })
    assert result.status == "success", result.result
    return target, result


def test_lf_file_stays_lf_after_a_one_line_edit(tmp_path):
    # A `#!/bin/sh` line terminated by CRLF is not a valid shebang, so a
    # one-line edit must not be allowed to rewrite the whole script.
    target, _ = _edit(
        tmp_path, "run.sh",
        b"#!/bin/sh\necho one\necho two\n",
        "echo two", "echo TWO",
    )

    assert target.read_bytes() == b"#!/bin/sh\necho one\necho TWO\n"


def test_crlf_file_stays_crlf_after_a_one_line_edit(tmp_path):
    # The mirror image: a Windows script must not be handed back as LF, which is
    # what a fix that merely stopped translating on write would produce.
    target, _ = _edit(
        tmp_path, "run.bat",
        b"@echo off\r\necho one\r\necho two\r\n",
        "echo two", "echo TWO",
    )

    assert target.read_bytes() == b"@echo off\r\necho one\r\necho TWO\r\n"


def test_mixed_endings_file_is_normalised_to_crlf(tmp_path):
    # detect_line_ending() reports CRLF when the file contains any CRLF at all,
    # so a mixed file is pinned to CRLF: a single stray LF is noise, and
    # guessing per line would let each edit reintroduce a second ending. Pinned
    # here so that rule cannot drift unnoticed.
    target, _ = _edit(
        tmp_path, "mixed.txt",
        b"one\r\ntwo\nthree\r\n",
        "three", "THREE",
    )

    data = target.read_bytes()
    assert data == b"one\r\ntwo\r\nTHREE\r\n"
    # No bare LF is left anywhere in the file.
    assert b"\n" not in data.replace(b"\r\n", b"")


def test_one_line_edit_reports_the_correct_diff(tmp_path):
    target, result = _edit(
        tmp_path, "sample.py",
        b"def foo():\n    x = 1\n    return x\n",
        "    x = 1", "    x = 2",
    )

    assert target.read_bytes() == b"def foo():\n    x = 2\n    return x\n"

    diff = result.result["diff"]
    # Only the edited line is reported as changed; the untouched lines must not
    # appear, because a line-ending rewrite would have shown every one of them.
    changed = [
        line for line in diff.splitlines()
        if (line.startswith("-") or line.startswith("+"))
        and not line.startswith(("---", "+++"))
    ]
    assert changed == ["-    x = 1", "+    x = 2"]
