from agent.skills.frontmatter import parse_metadata
from agent.skills.config import should_include_skill
from agent.skills.types import Skill, SkillEntry


def test_quoted_false_does_not_override_missing_requirements(monkeypatch):
    monkeypatch.delenv('COW_TEST_REQUIRED_KEY', raising=False)
    metadata = parse_metadata({'metadata': {'always': 'false', 'requires': {'env': ['COW_TEST_REQUIRED_KEY']}}})
    entry = SkillEntry(Skill('test', 'Test', '', '', 'custom', ''), metadata)
    assert metadata.always is False
    assert not should_include_skill(entry)


def test_json_boolean_strings_and_install_extract_are_normalized():
    metadata = parse_metadata({'metadata': '{"always":"false","default_enabled":"false","install":[{"kind":"download","extract":"false"}]}'})
    assert metadata.always is False
    assert metadata.default_enabled is False
    assert metadata.install[0].extract is False


def test_true_boolean_and_string_flags_remain_enabled():
    for value in [True, 'true', 'yes', 'on']:
        metadata = parse_metadata({'metadata': {'always': value}})
        assert metadata.always is True


def test_numeric_flags_keep_their_truthiness():
    metadata = parse_metadata({'metadata': {'always': 1, 'default_enabled': 0}})
    assert metadata.always is True
    assert metadata.default_enabled is False
