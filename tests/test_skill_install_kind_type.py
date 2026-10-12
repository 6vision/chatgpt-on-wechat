"""A malformed install ``kind:`` skips that entry instead of breaking skill loading."""

from pathlib import Path

import pytest
import yaml

from agent.skills.frontmatter import parse_metadata
from agent.skills.loader import SkillLoader


def _install(entry_yaml):
    meta = parse_metadata(yaml.safe_load("metadata:\n  cowagent:\n    install:\n" + entry_yaml))
    return [(spec.kind, spec.id) for spec in meta.install]


@pytest.mark.parametrize("raw", ["kind:", "kind: 1", "kind: [a]"])
def test_bad_kind_is_skipped(raw):
    assert _install(f"      - {raw}\n") == []


@pytest.mark.parametrize("raw, expected", [
    ("kind: npm\n        id: left-pad", [("npm", "left-pad")]),
    ("type: git", [("git", None)]),
    ("kind: '  NPM  '", [("npm", None)]),
])
def test_valid_kind_parses(raw, expected):
    assert _install(f"      - {raw}\n") == expected


def test_bad_skill_does_not_hide_the_others(tmp_path: Path):
    for name, extra in (("good", ""), ("bad", "\nmetadata:\n  cowagent:\n    install:\n      - kind:")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: d{extra}\n---\nbody\n", encoding="utf-8")
    entries = SkillLoader().load_all_skills(custom_dir=str(tmp_path))
    assert "good" in {getattr(e, "skill", e).name for e in entries.values()}
