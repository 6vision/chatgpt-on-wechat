from agent.skills.loader import SkillLoader
from agent.skills.frontmatter import parse_frontmatter, strip_frontmatter


def test_bom_skill_discovery_retains_metadata(tmp_path):
    skill_dir = tmp_path / 'example'
    skill_dir.mkdir()
    content = '\ufeff---\nname: example\ndescription: Read examples\n---\nBody\n'
    (skill_dir / 'SKILL.md').write_text(content, encoding='utf-8')
    result = SkillLoader().load_all_skills(custom_dir=str(tmp_path))
    assert 'example' in result
    assert result['example'].skill.description == 'Read examples'
    assert strip_frontmatter(content) == 'Body\n'
    assert parse_frontmatter(content)['name'] == 'example'


def test_literal_bom_in_markdown_body_is_retained():
    content = 'Body\n\ufeffliteral'
    assert strip_frontmatter(content) == content


def test_bom_config_preserves_runtime_disabled_choice(tmp_path):
    import json
    from agent.skills.manager import SkillManager
    builtin = tmp_path / 'builtin'
    builtin.mkdir()
    custom = tmp_path / 'skills'
    directory = custom / 'example'
    directory.mkdir(parents=True)
    (directory / 'SKILL.md').write_text('---\nname: example\ndescription: Test\n---\nBody\n')
    config = custom / 'skills_config.json'
    config.write_text('\ufeff' + json.dumps({'example': {'enabled': False}}), encoding='utf-8')
    manager = SkillManager(builtin_dir=str(builtin), custom_dir=str(custom))
    assert not manager.is_skill_enabled('example')
    assert json.loads(config.read_text(encoding='utf-8-sig'))['example']['enabled'] is False
