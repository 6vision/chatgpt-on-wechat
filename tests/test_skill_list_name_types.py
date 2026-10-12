import pytest
from agent.skills.loader import SkillLoader
from agent.skills.formatter import format_skill_entries_for_prompt


@pytest.mark.parametrize('value,expected', [('42', '42'), ('false', 'example'), ('{nested: value}', "{'nested': 'value'}")])
def test_list_name_scalar_is_normalized_before_catalog_and_prompt(tmp_path, value, expected):
    directory = tmp_path / 'example'
    directory.mkdir()
    (directory / 'SKILL.md').write_text(f'---\nname: [{value}]\ndescription: Test\n---\nBody\n')
    entries = SkillLoader().load_all_skills(custom_dir=str(tmp_path))
    assert expected in entries
    assert isinstance(entries[expected].skill.name, str)
    assert '<name>' in format_skill_entries_for_prompt(list(entries.values()))
