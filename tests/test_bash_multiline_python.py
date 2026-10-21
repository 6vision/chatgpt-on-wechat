"""Multiline Python must reach the interpreter intact on Windows cmd.exe."""

import os
import subprocess
import sys
import tempfile
import time

import pytest

from agent.tools.bash import background
from agent.tools.bash.bash import Bash


@pytest.mark.parametrize(
    "interpreter",
    ["python", "python3 -u", "py -3.11", r'"C:\Program Files\Python\python.exe"'],
)
def test_multiline_spill_preserves_program_and_script_arguments(interpreter):
    code = "import sys\nprint(sys.argv[1])"
    command = f'{interpreter} -c "{code}" "value with spaces"'
    rewritten, path = Bash._rewrite_long_python_c(command, standalone=True)
    try:
        assert path is not None
        with open(path, encoding="utf-8") as source:
            assert source.read() == code
        assert rewritten.startswith(interpreter + " ")
        assert rewritten.endswith(' "value with spaces"')
        result = subprocess.run(
            [sys.executable, path, "value with spaces"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "value with spaces"
    finally:
        if path:
            os.unlink(path)


@pytest.mark.parametrize(
    "command",
    [
        'echo python -c "value=40\nprint(value+2)"',
        'node -c "value=40\nprint(value+2)"',
        'python -c "value=40\nprint(value+2)" && echo "another command"',
        'python -c "value=40\nprint(value+2)" > result.txt',
        'python -c "value=40\nprint(value+2)""concatenated quote"',
    ],
)
def test_multiline_spill_does_not_reinterpret_other_shell_commands(command):
    assert Bash._rewrite_long_python_c(command, standalone=True) == (command, None)


WINDOWS_PROGRAMS = [
    ("lf", "value=40\nprint(value+2)", "", "", ["42"]),
    ("crlf", "value=40\r\nprint(value+2)", "", "", ["42"]),
    ("block", "for value in [40]:\n    print(value+2)", "", "", ["42"]),
    ("quoted", 'print("first")\nprint("second")', "", "", ["first", "second"]),
    (
        "arguments",
        "import sys\nprint(sys.argv[1])",
        " -u",
        ' "argument with spaces"',
        ["argument with spaces"],
    ),
]


@pytest.mark.skipif(not Bash._IS_WIN, reason="native Windows cmd.exe integration")
@pytest.mark.parametrize(
    "_label,code,flags,suffix,expected",
    WINDOWS_PROGRAMS,
    ids=[p[0] for p in WINDOWS_PROGRAMS],
)
def test_windows_multiline_python_executes_every_line(
    tmp_path, monkeypatch, _label, code, flags, suffix, expected
):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    escaped = code.replace('"', '\\"')
    command = f'"{sys.executable}"{flags} -c "{escaped}"{suffix}'
    assert len(command) < Bash._WIN_CMD_SAFE_LEN
    result = Bash({"cwd": str(tmp_path)}).execute({"command": command, "timeout": 10})
    assert result.status == "success", result.result
    assert result.result["exit_code"] == 0
    assert result.result["output"].splitlines() == expected
    assert list(tmp_path.glob("bash-pyc-*.py")) == []


@pytest.mark.skipif(
    not Bash._IS_WIN, reason="native Windows cmd.exe background integration"
)
def test_windows_background_multiline_python_retains_all_output(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    tool = Bash({"cwd": str(tmp_path)})
    result = tool.execute(
        {
            "command": f'"{sys.executable}" -c "value=40\nprint(value+2)"',
            "run_in_background": True,
        }
    )
    assert result.status == "success", result.result
    job_id = result.result["bash_id"]
    output = ""
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = background.read(job_id)
            output += status["output"]
            if not status["running"]:
                break
            time.sleep(0.05)
        assert not status["running"]
        assert status["exit_code"] == 0
        assert output.splitlines() == ["42"]
        assert list(tmp_path.glob("bash-pyc-*.py")) == []
    finally:
        background.kill(job_id)
