import os
import shutil
import time

import pytest

from agent.tools.search_files.search_files import SearchFiles

# Tier 3 of the 4-tier backend list: the only one available on a stock Windows
# box (no rg, no grep). Its script is assembled in Python and handed to
# `powershell -Command`, so any value interpolated into a quoted position in
# that script has to be escaped for PowerShell's parser, not Python's.

Q = chr(39)  # built at runtime so this test file is itself quotable

pytestmark = pytest.mark.skipif(
    os.name != "nt" or not (shutil.which("powershell") or shutil.which("pwsh")),
    reason="PowerShell backend is Windows-only and needs a PowerShell on PATH",
)


def _apostrophe_tree(tmp_path):
    """A search root whose name holds an apostrophe, with a known token in it."""
    root = tmp_path / ("O" + Q + "Brien")
    root.mkdir()
    (root / "notes.txt").write_text("foundme inside an apostrophe dir\n", encoding="utf-8")
    return root


def _powershell_tool(tmp_path):
    # Pin the backend explicitly instead of letting _pick_backend choose: on a
    # developer box with rg installed this is tier 1 and the test would pass
    # vacuously while exercising nothing.
    tool = SearchFiles({"cwd": str(tmp_path)})
    tool._pick_backend = lambda: tool._backend_powershell
    return tool


def _opts(root):
    from agent.tools.search_files.search_files import _SearchOptions

    return _SearchOptions(
        pattern="foundme", root=str(root), file_glob="*", output_mode="content",
        ignore_case=True, no_ignore=False, max_results=50,
        deadline=time.monotonic() + 30,
    )


def _fail_every_powershell_run(monkeypatch):
    """Make the backend's subprocess.run return what a rejected script does."""
    import subprocess

    class _Failed:
        returncode = 1
        stdout = ""
        stderr = "The string is missing the terminator: '."

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Failed())


# ------------------------------------------------------------- the quoting bug


def test_search_root_with_an_apostrophe_still_finds_its_matches(tmp_path):
    root = _apostrophe_tree(tmp_path)

    result = _powershell_tool(tmp_path).execute({"pattern": "foundme", "path": str(root)})

    assert result.status == "success"
    # Unquoted, the apostrophe closed the -LiteralPath literal early and
    # PowerShell refused to parse the whole script, so this came back an empty
    # success while stderr said "The string is missing the terminator: '.".
    assert result.result["match_count"] == 1
    assert [m["file"] for m in result.result["matches"]] == ["notes.txt"]
    assert result.result["matches"][0]["line"] == 1


def test_empty_result_for_an_apostrophe_root_is_not_a_hidden_failure(tmp_path):
    # The flip side of the quoting bug: with no rows to return, a script that
    # failed to parse was indistinguishable from a genuine no-match. A token
    # that is genuinely absent must still be a plain empty success.
    root = _apostrophe_tree(tmp_path)

    result = _powershell_tool(tmp_path).execute({"pattern": "not_present_anywhere", "path": str(root)})

    assert result.status == "success"
    assert result.result["matches"] == []
    assert result.result["match_count"] == 0


def test_file_glob_with_an_apostrophe_reaches_the_backend_intact(tmp_path):
    root = _apostrophe_tree(tmp_path)
    (root / ("keep" + Q + "me.txt")).write_text("foundme glob\n", encoding="utf-8")

    result = _powershell_tool(tmp_path).execute(
        {"pattern": "foundme", "path": str(root), "file_glob": "*" + Q + "me.txt", "output_mode": "files"}
    )

    assert result.status == "success"
    assert result.result["files"] == ["keep" + Q + "me.txt"]


def test_ps_quote_doubles_apostrophes_and_wraps_once():
    from agent.tools.search_files.search_files import _ps_quote

    assert _ps_quote("O" + Q + "Brien") == "'O" + Q + Q + "Brien'"
    assert _ps_quote("plain/path") == "'plain/path'"
    assert _ps_quote("") == "''"


# ------------------------------------------- a failed run must not read as empty


def test_powershell_backend_reports_a_non_zero_exit_instead_of_swallowing_it(tmp_path, monkeypatch):
    # The exit code and stderr used to be dropped on the floor. Anything that
    # made the script fail - a parse error, a root that vanished between the
    # exists() check and the run - reached the model as a successful search of
    # zero matches, with no signal that anything went wrong.
    _fail_every_powershell_run(monkeypatch)

    with pytest.raises(RuntimeError, match="powershell exited 1"):
        _powershell_tool(tmp_path)._backend_powershell(_opts(_apostrophe_tree(tmp_path)))


def test_failed_powershell_run_does_not_report_a_successful_empty_search(tmp_path, monkeypatch):
    # End of the chain: a failed run is retried on the python backend, so the
    # model gets the match that IS in the file rather than "0 matches".
    root = _apostrophe_tree(tmp_path)
    _fail_every_powershell_run(monkeypatch)

    result = _powershell_tool(tmp_path).execute({"pattern": "foundme", "path": str(root)})

    assert result.status == "success"
    assert result.result["match_count"] == 1
    assert result.result["matches"][0]["file"] == "notes.txt"
