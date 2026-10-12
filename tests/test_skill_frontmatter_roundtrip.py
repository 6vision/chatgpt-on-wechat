"""A created skill must survive the loader's own frontmatter parser.

The console form writes ``description: <原文>`` into SKILL.md and the loader
reads it back with PyYAML. YAML 1.1 resolves a plain ``no`` / ``off`` /
``1:30`` to a bool/int, so a user-typed description can come back changed -
or as nothing, and a skill with no description is dropped from every list.
"""

import pytest

from agent.skills.frontmatter import parse_frontmatter
from agent.skills.service import render_skill_md


# Descriptions that already round-trip; they pin the intended behavior.
PLAIN_SAFE = [
    "ordinary skill",
    'Use when: a "quoted" case',
    "Explain these fields: name, description",
    "- not a list",
    "# not a comment",
]

# User-typable descriptions a plain YAML 1.1 scalar does not read back as-is.
NON_ROUND_TRIPPING = [
    "no", "off", "false", "null", "~",       # -> False / None
    "yes", "on", "true",                     # -> True
    "1:30", "12:34:56",                      # -> sexagesimal ints
    "0x1f", ".inf", "2026-10-12",            # -> int / float / date
]


@pytest.mark.parametrize("description", PLAIN_SAFE + NON_ROUND_TRIPPING)
def test_render_then_parse_keeps_the_description_string(description):
    text = render_skill_md("demo", description)
    assert parse_frontmatter(text)["description"] == description


def test_a_created_skill_with_a_yaml_keyword_description_is_not_dropped(tmp_path):
    from agent.skills.manager import SkillManager
    from agent.skills.service import SkillService

    builtin = tmp_path / "builtin"
    custom = tmp_path / "workspace" / "skills"
    builtin.mkdir(parents=True, exist_ok=True)
    custom.mkdir(parents=True, exist_ok=True)
    service = SkillService(SkillManager(builtin_dir=str(builtin), custom_dir=str(custom)))

    service.create({"name": "deny", "description": "no"})

    entry = service.manager.get_skill("deny")
    assert entry is not None, "the loader dropped a YAML 1.1 keyword skill"
    assert entry.skill.description == "no"
