"""The public knowledge CLI must show the documents its service persists."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[1]
PROGRAM = """
import json
from pathlib import Path
from click.testing import CliRunner
from agent.knowledge.service import KnowledgeService
from cli.commands.knowledge import knowledge
class Storage:
    def delete_by_path(self, path): pass
class OwnedIndex:
    storage = Storage()
    def mark_dirty(self): pass
    async def sync(self): pass
workspace = Path('workspace').resolve()
service = KnowledgeService(str(workspace), OwnedIndex())
paths = json.loads(Path('documents.json').read_text(encoding='utf-8'))
persisted = [service.create_document(path, '# Owned guide\\n') for path in paths]
if Path('non-symbolic-link-boundary').exists():
    from unittest.mock import patch
    # Model a directory junction's classification using a real owned alias.
    with patch('os.path.islink', return_value=False):
        result = CliRunner().invoke(knowledge, ['list'])
else:
    result = CliRunner().invoke(knowledge, ['list'])
print(json.dumps({'persisted': persisted, 'exit': result.exit_code, 'output': result.output}))
"""


def invoke(tmp_path, documents, cycle=False, root_link=False, junction_boundary=False):
    home, data, workspace = (tmp_path / name for name in ('home', 'data', 'workspace'))
    home.mkdir()
    data.mkdir()
    (workspace / 'knowledge').mkdir(parents=True)
    if root_link:
        target = tmp_path / 'shared-knowledge'
        target.mkdir()
        (workspace / 'knowledge').rmdir()
        try:
            (workspace / 'knowledge').symlink_to(target, target_is_directory=True)
        except OSError:
            pytest.skip('directory symlinks unavailable')
    if cycle:
        try:
            (workspace / 'knowledge' / 'cycle').symlink_to(
                workspace / 'knowledge', target_is_directory=True
            )
        except OSError:
            pytest.skip('directory symlinks unavailable')
    (data / 'config.json').write_text(json.dumps({'agent_workspace': str(workspace)}), encoding='utf-8')
    (tmp_path / 'documents.json').write_text(json.dumps(documents), encoding='utf-8')
    if junction_boundary:
        (tmp_path / 'non-symbolic-link-boundary').touch()
    env = {
        'PATH': os.environ.get('PATH', ''),
        'HOME': str(home), 'USERPROFILE': str(home), 'COW_DATA_DIR': str(data),
        'PYTHONPATH': os.pathsep.join([str(REPO), *sys.path]),
        'PYTHONDONTWRITEBYTECODE': '1',
    }
    assert workspace.resolve().is_relative_to(tmp_path.resolve())
    result = subprocess.run([sys.executable, '-c', PROGRAM], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload['exit'] == 0, payload['output']
    assert [row['path'] for row in payload['persisted']] == documents
    assert all((workspace / 'knowledge' / path).is_file() for path in documents)
    return payload['output']


@pytest.mark.parametrize(('documents', 'expected'), [
    (['guide.md'], ['guide']),
    (['engineering/api/guide.md'], ['engineering/ (1)', 'api/ (1)', 'guide']),
    (['root.md', 'engineering/flat.md', 'engineering/api/nested.md'],
     ['root', 'engineering/ (2)', 'flat', 'api/ (1)', 'nested']),
    (['engineering/api/one.md', 'operations/api/two.md'],
     ['engineering/ (1)', 'operations/ (1)', 'one', 'two']),
])
def test_public_tree_shows_all_service_document_locations(tmp_path, documents, expected):
    output = invoke(tmp_path, documents)
    assert '(empty)' not in output
    for item in expected:
        assert item in output
    assert 'index' not in output


def test_truly_empty_knowledge_remains_empty(tmp_path):
    assert '(empty)' in invoke(tmp_path, [])


def test_existing_flat_category_keeps_its_files_and_count(tmp_path):
    output = invoke(tmp_path, ['engineering/one.md', 'engineering/two.md'])
    assert 'engineering/ (2)' in output
    assert 'one' in output and 'two' in output


def test_existing_file_display_limit_remains_bounded(tmp_path):
    output = invoke(tmp_path, [f'engineering/doc-{i:02}.md' for i in range(17)])
    assert 'engineering/ (17)' in output
    assert 'doc-14' in output and 'doc-15' not in output
    assert '+2 more' in output


def test_directory_link_does_not_recurse_into_its_parent(tmp_path):
    output = invoke(tmp_path, ['guide.md'], cycle=True)
    assert output.count('cycle/') == 1
    assert 'guide' in output
    assert len(output) < 1000


def test_selected_knowledge_root_link_retains_category_display(tmp_path):
    output = invoke(tmp_path, ['engineering/guide.md'], root_link=True)
    assert 'engineering/ (1)' in output
    assert 'guide' in output


def test_canonical_parent_alias_is_bounded_when_not_classified_as_symbolic(tmp_path):
    output = invoke(tmp_path, ['guide.md'], cycle=True, junction_boundary=True)
    assert output.count('cycle/') == 1
    assert 'guide' in output
    assert len(output) < 1000
