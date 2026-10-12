"""Nonempty whitespace oldText remains an exact replacement request."""

import pytest

from agent.tools.edit.edit import Edit


@pytest.mark.parametrize("content,old,new,replace_all,status,expected", [
    (b"First\n\nSecond\n", "\n\n", "\n---\n", False, "success", b"First\n---\nSecond\n"),
    (b"First Second", " ", "_", False, "success", b"First_Second"),
    (b"First\tSecond", "\t", "_", False, "success", b"First_Second"),
    (b"First\r\n\r\nSecond\r\n", "\r\n\r\n", "\n---\n", False, "success", b"First\r\n---\r\nSecond\r\n"),
    (b"First\n\nSecond\n\nThird\n", "\n\n", "\n", False, "error", b"First\n\nSecond\n\nThird\n"),
    (b"First\n\nSecond\n\nThird\n", "\n\n", "\n", True, "success", b"First\nSecond\nThird\n"),
    (b"FirstSecond", " ", "_", False, "error", b"FirstSecond"),
    (b"First", "", "Second", False, "success", b"First\nSecond"),
])
def test_whitespace_replacement_contract(tmp_path, content, old, new, replace_all, status, expected):
    path = tmp_path / "notes.txt"
    path.write_bytes(content)
    outcome = Edit({"cwd": str(tmp_path)}).execute({
        "path": "notes.txt", "oldText": old, "newText": new, "replaceAll": replace_all,
    })
    assert outcome.status == status, outcome.result
    assert path.read_bytes() == expected
