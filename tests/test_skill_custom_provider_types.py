import json
import pytest
from agent.skills.config import has_custom_provider, should_include_skill, get_missing_requirements
from agent.skills.frontmatter import parse_metadata
from agent.skills.types import Skill, SkillEntry


@pytest.mark.parametrize('field,value', [('api_key', 42), ('api_base', ['invalid']), ('api_key', {'invalid': True})])
def test_malformed_provider_does_not_break_skill_requirements(monkeypatch, field, value):
    payload = {'api_key': 'fake-test-key', 'api_base': 'https://example.invalid'}
    payload[field] = value
    monkeypatch.setenv('SKILL_IMAGE_GENERATION_CUSTOM_PROVIDER', json.dumps(payload))
    monkeypatch.delenv('COW_TEST_MISSING_KEY', raising=False)
    entry = SkillEntry(Skill('image-generation', 'Test', '', '', 'custom', ''), parse_metadata({'metadata': {'requires': {'anyEnv': ['COW_TEST_MISSING_KEY']}}}))
    assert not has_custom_provider('image-generation')
    assert not should_include_skill(entry)
    assert get_missing_requirements(entry) == {'anyEnv': ['COW_TEST_MISSING_KEY']}


def test_valid_provider_still_satisfies_custom_configuration(monkeypatch):
    monkeypatch.setenv('SKILL_IMAGE_GENERATION_CUSTOM_PROVIDER', '{"api_key":" test ","api_base":" https://example.invalid "}')
    assert has_custom_provider('image-generation')
