import json
from cli.commands import skill

def test_install_preserves_existing_bom_config(tmp_path, monkeypatch):
    monkeypatch.setattr(skill, '_target_skills_dir', lambda agent_id=None: str(tmp_path))
    (tmp_path / 'skills_config.json').write_text('\ufeff{"existing":{"name":"existing","enabled":false}}', encoding='utf-8')
    skill._register_installed_skill('new', 'local')
    config = json.loads((tmp_path / 'skills_config.json').read_text(encoding='utf-8-sig'))
    assert config['existing'] == {'name': 'existing', 'enabled': False}
    assert config['new']['name'] == 'new'
