from agent.skills.manager import SkillManager


def test_non_model_invocable_unavailable_skill_is_absent_from_prompt(tmp_path, monkeypatch):
    monkeypatch.delenv('COW_TEST_UNCONFIGURED', raising=False)
    builtin = tmp_path / 'builtin'
    builtin.mkdir()
    custom = tmp_path / 'skills'
    for name, hidden in [('manual-only', True), ('visible', False)]:
        directory = custom / name
        directory.mkdir(parents=True)
        (directory / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: A test skill\ndisable-model-invocation: {str(hidden).lower()}\nmetadata:\n  requires:\n    env: [COW_TEST_UNCONFIGURED]\n---\n## Setup\nConfigure a fake test key\n')
    manager = SkillManager(builtin_dir=str(builtin), custom_dir=str(custom))
    assert manager.get_skill('manual-only') is not None
    prompt = manager.build_skills_prompt()
    assert 'manual-only' not in prompt
    assert 'visible' in prompt
    assert 'COW_TEST_UNCONFIGURED' in prompt
