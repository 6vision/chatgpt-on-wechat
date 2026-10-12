"""Local skill installs must never remove or recursively copy their own source."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[1]
SKILL = b"---\nname: notes\ndescription: owned fixture\n---\n# Notes\n"


def _write_skill(path, payload):
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_bytes(SKILL)
    (path / "notes.txt").write_bytes(payload)


def _invoke(tmp_path, source, workspace):
    home, data = tmp_path / "home", tmp_path / "data"
    home.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    (data / "config.json").write_text(
        json.dumps({"agent_workspace": str(workspace)}), encoding="utf-8"
    )
    # Do not inherit operator COW_* settings, HOME, credentials or state roots.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "COW_DATA_DIR": str(data),
        "PYTHONPATH": os.pathsep.join([str(REPO), *sys.path]),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    assert source.resolve().is_relative_to(tmp_path.resolve())
    assert workspace.resolve().is_relative_to(tmp_path.resolve())
    return subprocess.run(
        [sys.executable, "-c", "from cli.commands.skill import skill; skill()",
         "install", str(source)],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=10,
    )


@pytest.mark.parametrize("kind", ["direct", "alias", "batch", "batch_alias", "source_in_target", "target_in_source"])
def test_public_install_refuses_overlapping_local_directories(tmp_path, kind):
    workspace = tmp_path / "workspace"
    target = workspace / "skills" / "notes"
    _write_skill(target, b"existing user notes\n")
    source = target
    if kind in {"batch", "batch_alias"}:
        source = target.parent
    if kind in {"alias", "batch_alias"}:
        alias = tmp_path / "alias"
        try:
            alias.symlink_to(source, target_is_directory=True)
        except OSError:
            pytest.skip("directory symlinks unavailable")
        source = alias
    if kind == "source_in_target":
        source = target / "nested"
        _write_skill(source, b"nested source notes\n")
    if kind == "target_in_source":
        source = workspace
        _write_skill(source, b"ancestor source notes\n")
    original = {str(p.relative_to(workspace)): p.read_bytes()
                for p in workspace.rglob("*") if p.is_file()}
    result = _invoke(tmp_path, source, workspace)
    current = {str(p.relative_to(workspace)): p.read_bytes()
               for p in workspace.rglob("*") if p.is_file()}
    assert current == original, result.stderr
    assert result.returncode == 1
    assert "overlap" in result.stderr.lower()
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("source_in_skills", [False, True])
def test_public_install_replaces_disjoint_target_and_retains_source(tmp_path, source_in_skills):
    workspace = tmp_path / "workspace"
    target = workspace / "skills" / "notes"
    _write_skill(target, b"prior version\n")
    source = (target.parent / "renamed-source") if source_in_skills else tmp_path / "source"
    _write_skill(source, b"updated skill\n")
    result = _invoke(tmp_path, source, workspace)
    assert result.returncode == 0, result.stderr
    assert (target / "SKILL.md").read_bytes() == SKILL
    assert (target / "notes.txt").read_bytes() == b"updated skill\n"
    assert (source / "SKILL.md").read_bytes() == SKILL
    assert (source / "notes.txt").read_bytes() == b"updated skill\n"
    config = json.loads((target.parent / "skills_config.json").read_text(encoding="utf-8"))
    assert config["notes"]["enabled"] is True
    assert config["notes"]["source"] == "local"
