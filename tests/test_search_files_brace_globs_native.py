"""SearchFiles brace globs behave the same on the rg, grep and Python backends."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.tools.search_files.search_files import SearchFiles

_NAMES = ["one.ts", "two.tsx", "three.py", "literal.{name}.ts", "literal.{ts,tsx}.ts", "{bracket}.ts", "[literal].ts"]


def _populate(directory, names):
    directory.mkdir()
    for name in names:
        (directory / name).write_text("TARGET\n", encoding="utf-8")


@pytest.fixture(params=["rg", "grep", "python"])
def tool(request, tmp_path, monkeypatch):
    binary = shutil.which(request.param) if request.param != "python" else None
    if request.param != "python" and (os.name == "nt" or not binary):
        pytest.skip("native POSIX search binary unavailable")
    source, bin_dir = tmp_path / "source", tmp_path / "bin"
    _populate(source, _NAMES)
    bin_dir.mkdir()
    if binary:
        (bin_dir / request.param).symlink_to(binary)
    monkeypatch.setenv("PATH", str(bin_dir))
    tool = SearchFiles({"cwd": str(source)})
    assert tool._pick_backend().__name__ == "_backend_" + request.param
    return tool


def _search(tool, glob, mode="files", **extra):
    return tool.execute({"pattern": "TARGET", "file_glob": glob, "output_mode": mode, **extra})


@pytest.mark.parametrize("glob, expected", [
    ("*.{ts,tsx}", sorted(set(_NAMES) - {"three.py"})),
    ("o*.{ts,py}", ["one.ts"]),
    ("*.{js,jsx}", []),
    ("*.tsx", ["two.tsx"]),
    (r"literal.\{name\}.ts", ["literal.{name}.ts"]),
    (r"literal.\{ts,tsx\}.ts", ["literal.{ts,tsx}.ts"]),
    ("[{]*.ts", ["{bracket}.ts"]),
    (r"\[literal\].{ts,tsx}", ["[literal].ts"]),
])
def test_brace_alternatives_and_escaped_literals(tool, glob, expected):
    result = _search(tool, glob)
    assert result.status == "success", result.result
    assert (result.result["files"], result.result["match_count"]) == (expected, len(expected))


def test_brace_filter_applies_to_content_and_count_modes(tool):
    content, count = _search(tool, "o*.{ts,tsx}", "content"), _search(tool, "o*.{ts,tsx}", "count")
    assert content.result["matches"] == [{"file": "one.ts", "line": 1, "match": "TARGET"}]
    assert count.result["counts"] == [{"file": "one.ts", "count": 1}]
    assert content.result["match_count"] == count.result["match_count"] == 1


@pytest.mark.parametrize("glob", ["{a,b}" * 20, "{" + ",".join(str(i) for i in range(257)) + "}"])
def test_oversized_brace_expansion_is_an_explicit_error(tool, glob):
    result = _search(tool, glob)
    assert result.status == "error"
    assert "file_glob exceeds 256 expanded alternatives" in result.result
    assert "use a narrower filter" in result.result


@pytest.mark.parametrize("glob", ["[]{a,b}]*.ts", "[!]{a,b}]*.ts"])
def test_initial_closing_bracket_keeps_braces_inside_character_class(tool, glob):
    source = Path(tool.cwd) / "classes"
    _populate(source, [",hit.ts", "ahit.ts", "bhit.ts", "]hit.ts", "{hit.ts", "}hit.ts", "xhit.ts"])
    expected = ["xhit.ts"] if "!" in glob else [",hit.ts", "]hit.ts", "ahit.ts", "bhit.ts", "{hit.ts", "}hit.ts"]
    if "!" in glob and tool._pick_backend().__name__ == "_backend_grep":
        # GNU and BSD grep disagree on negated --include classes; compare to raw grep output.
        native = subprocess.run([shutil.which("grep"), "-rlE", f"--include={glob}", "-e", "TARGET", str(source)],
                                capture_output=True, text=True, check=False)
        assert native.returncode in (0, 1), native.stderr
        expected = sorted(Path(line).name for line in native.stdout.splitlines())
    result = _search(tool, glob, path=str(source))
    assert result.status == "success", result.result
    assert (result.result["files"], result.result["match_count"]) == (expected, len(expected))
