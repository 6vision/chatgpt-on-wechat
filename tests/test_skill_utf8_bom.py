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
