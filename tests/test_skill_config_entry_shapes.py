import json
import pytest
from agent.skills.manager import SkillManager


@pytest.mark.parametrize('damaged', [None, [], 3, 'invalid'])
def test_bad_entry_does_not_lose_valid_skill_choices(tmp_path, damaged):
    builtin = tmp_path / 'builtin'
    builtin.mkdir()
    custom = tmp_path / 'skills'
    for name in ['damaged', 'healthy']:
        directory = custom / name
        directory.mkdir(parents=True)
        (directory / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: Test\n---\nBody\n')
    config_path = custom / 'skills_config.json'
    config_path.write_text(json.dumps({'damaged': damaged, 'healthy': {'enabled': False, 'display_name': 'Kept'}}))
    manager = SkillManager(builtin_dir=str(builtin), custom_dir=str(custom))
    assert manager.get_skill('damaged') is not None
    assert not manager.is_skill_enabled('healthy')
    assert manager.skills_config['healthy']['display_name'] == 'Kept'
    assert isinstance(json.loads(config_path.read_text())['damaged'], dict)
