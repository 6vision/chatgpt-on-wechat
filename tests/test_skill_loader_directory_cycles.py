"""Directory aliases must not turn skill discovery into a recursive loop."""

import subprocess
import sys

import pytest

from agent.skills.loader import SkillLoader


def _symlink(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"native directory symlinks unavailable: {exc}")


def _skill(root):
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nname: linked-skill\ndescription: A linked skill pack\n---\nInstructions\n",
        encoding="utf-8",
    )


def test_parent_directory_links_do_not_expand_discovery_forever(tmp_path):
    root = tmp_path / "skills"
    _skill(root / "pack")
    # Two edges back to the ancestor turn a tree walk into exponential work.
    _symlink(root / "back-one", root)
    _symlink(root / "back-two", root)
    result = subprocess.run(
        [sys.executable, "-c", (
            "import sys; from agent.skills.loader import SkillLoader; "
            "result = SkillLoader().load_skills_from_dir(sys.argv[1], 'custom'); "
            "assert len(result.skills) == 1, len(result.skills); "
            "assert result.diagnostics"
        ), str(root)],
        text=True, capture_output=True, timeout=3,
    )
    assert result.returncode == 0, result.stderr


def test_legitimate_linked_skill_collection_is_still_loaded(tmp_path):
    collection = tmp_path / "shared-pack"
    _skill(collection / "nested-skill")
    root = tmp_path / "skills"
    root.mkdir()
    _symlink(root / "linked-pack", collection)

    result = SkillLoader().load_skills_from_dir(str(root), "custom")
    assert [skill.name for skill in result.skills] == ["linked-skill"]
    assert not result.diagnostics
