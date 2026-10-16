import json
from cli.commands import skill

def test_install_preserves_existing_bom_config(tmp_path, monkeypatch):
    monkeypatch.setattr(skill, '_target_skills_dir', lambda agent_id=None: str(tmp_path))
    (tmp_path / 'skills_config.json').write_text('\ufeff{"existing":{"name":"existing","enabled":false}}', encoding='utf-8')
    skill._register_installed_skill('new', 'local')
    config = json.loads((tmp_path / 'skills_config.json').read_text(encoding='utf-8-sig'))
    assert config['existing'] == {'name': 'existing', 'enabled': False}
    assert config['new']['name'] == 'new'


def test_enable_preserves_bom_config_other_choices(tmp_path, monkeypatch):
    monkeypatch.setattr(skill, 'get_skills_dir', lambda: str(tmp_path))
    path = tmp_path / 'skills_config.json'
    path.write_text('\ufeff{"target":{"enabled":false},"other":{"enabled":false}}', encoding='utf-8')
    skill._set_enabled('target', True)
    config = json.loads(path.read_text())
    assert config['target']['enabled'] is True
    assert config['other']['enabled'] is False


def test_uninstall_removes_bom_config_registration(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    monkeypatch.setattr(skill, 'get_skills_dir', lambda: str(tmp_path))
    monkeypatch.setitem(sys.modules, 'agent.admin', SimpleNamespace(get_agent_admin_service=lambda: SimpleNamespace(prune_skill=lambda name: None)))
    (tmp_path / 'removed').mkdir()
    path = tmp_path / 'skills_config.json'
    path.write_text('\ufeff{"removed":{"enabled":true},"other":{"enabled":false}}', encoding='utf-8')
    skill.uninstall.callback('removed', True)
    assert not (tmp_path / 'removed').exists()
    assert json.loads(path.read_text()) == {'other': {'enabled': False}}
