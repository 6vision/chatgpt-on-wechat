"""Documented brace globs use actual installed backends and the Python fallback."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from agent.tools.search_files.search_files import SearchFiles


@pytest.fixture(params=["rg", "grep", "python"])
def backend_tool(request, tmp_path, monkeypatch):
    backend = request.param
    binary = shutil.which(backend) if backend != "python" else None
    if backend != "python" and (os.name == "nt" or not binary):
        pytest.skip("native POSIX search binary unavailable")
    source = tmp_path / "source"
    source.mkdir()
    for name in ["one.ts", "two.tsx", "three.py", "literal.{name}.ts", "literal.{ts,tsx}.ts", "{bracket}.ts", "[literal].ts"]:
        (source / name).write_text("TARGET\n", encoding="utf-8")
    native_bin = tmp_path / "bin"
    native_bin.mkdir()
    if binary:
        (native_bin / backend).symlink_to(binary)
    # Availability is real PATH discovery; no backend or subprocess is replaced.
    monkeypatch.setenv("PATH", str(native_bin))
    tool = SearchFiles({"cwd": str(source)})
    assert tool._pick_backend().__name__ == "_backend_" + backend
    return tool


@pytest.mark.parametrize(
    "glob, expected",
    [
        ("*.{ts,tsx}", ["[literal].ts", "literal.{name}.ts", "literal.{ts,tsx}.ts", "one.ts", "two.tsx", "{bracket}.ts"]),
        ("o*.{ts,py}", ["one.ts"]),
        ("*.{js,jsx}", []),
        ("*.tsx", ["two.tsx"]),
        (r"literal.\{name\}.ts", ["literal.{name}.ts"]),
        (r"literal.\{ts,tsx\}.ts", ["literal.{ts,tsx}.ts"]),
        ("[{]*.ts", ["{bracket}.ts"]),
        (r"\[literal\].{ts,tsx}", ["[literal].ts"]),
    ],
)
def test_file_glob_filters_preserve_documented_alternatives_and_literals(backend_tool, glob, expected):
    result = backend_tool.execute({"pattern": "TARGET", "file_glob": glob, "output_mode": "files"})
    assert result.status == "success", result.result
    assert result.result["files"] == expected
    assert result.result["match_count"] == len(expected)


@pytest.mark.parametrize("mode", ["content", "count"])
def test_brace_filter_applies_to_other_output_modes(backend_tool, mode):
    result = backend_tool.execute({"pattern": "TARGET", "file_glob": "o*.{ts,tsx}", "output_mode": mode})
    assert result.status == "success", result.result
    assert result.result["match_count"] == 1
    if mode == "count":
        assert result.result["counts"] == [{"file": "one.ts", "count": 1}]
    else:
        assert result.result["matches"] == [{"file": "one.ts", "line": 1, "match": "TARGET"}]


@pytest.mark.parametrize("glob", ["{a,b}" * 20, "{" + ",".join(str(i) for i in range(257)) + "}"])
def test_oversized_brace_expansion_is_an_explicit_error(backend_tool, glob):
    result = backend_tool.execute({"pattern": "TARGET", "file_glob": glob, "output_mode": "files"})
    assert result.status == "error"
    assert "file_glob exceeds 256 expanded alternatives" in result.result
    assert "use a narrower filter" in result.result


@pytest.mark.parametrize("glob, negative", [("[]{a,b}]*.ts", False), ("[!]{a,b}]*.ts", True)])
def test_initial_closing_bracket_keeps_braces_inside_character_class(backend_tool, glob, negative):
    source = Path(backend_tool.cwd) / "classes"
    source.mkdir()
    for name in [",hit.ts", "ahit.ts", "bhit.ts", "]hit.ts", "{hit.ts", "}hit.ts", "xhit.ts"]:
        (source / name).write_text("TARGET\n", encoding="utf-8")
    result = backend_tool.execute({"pattern": "TARGET", "path": str(source), "file_glob": glob, "output_mode": "files"})
    assert result.status == "success", result.result
    if negative:
        expected = ["xhit.ts"]
        if backend_tool._pick_backend().__name__ == "_backend_grep":
            # GNU/BSD include matchers differ here. Compare to the actual raw
            # native producer, without the tool's brace expansion or parser.
            native = subprocess.run(
                [shutil.which("grep"), "-rH", "-E", f"--include={glob}", "-l", "-e", "TARGET", str(source)],
                capture_output=True, text=True, check=False,
            )
            assert native.returncode in (0, 1), native.stderr
            expected = [Path(line).name for line in native.stdout.splitlines()]
    else:
        expected = [",hit.ts", "ahit.ts", "bhit.ts", "]hit.ts", "{hit.ts", "}hit.ts"]
    expected = sorted(expected)
    assert result.result["files"] == expected
    assert result.result["match_count"] == len(expected)
