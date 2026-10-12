"""Documents admitted by the public service remain visible and searchable."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[1]
PROGRAM = r"""
import asyncio
import json
import sys
from pathlib import Path
from click.testing import CliRunner
from agent.knowledge.service import KnowledgeService
from agent.memory.config import MemoryConfig
from agent.memory.manager import MemoryManager
from agent.memory.storage import MemoryStorage
from cli.commands.knowledge import knowledge
workspace = Path(sys.argv[1]).resolve()
extension, action = sys.argv[2:]
manager = MemoryManager(MemoryConfig(workspace_root=str(workspace)), embedding_provider=None)
service = KnowledgeService(str(workspace), manager)
source = 'category/guide.' + extension
target = 'category/target.' + extension
content = '# Owned guide\n\nquasarorchid knowledge test\n\n[Target](target.' + extension + '#anchor)\n'
try:
    first = service.dispatch('create_document', {
        'path': source,
        'content': content,
    })
    second = service.dispatch('create_document', {
        'path': target, 'content': '# Owned target\n',
    })
    assert first['code'] == second['code'] == 200
    assert service.dispatch('read', {'path': source})['code'] == 200
    if action == 'rename':
        index = workspace / 'knowledge/index.md'
        index.write_text('- [Owned guide](./' + source + ') — Retain summary\n', encoding='utf-8')
        result = service.dispatch('rename_category', {'path': 'category', 'new_path': 'renamed'})
        assert result['code'] == 200
        assert result['payload']['moved_documents'] == 2
        assert manager.storage.get_file_hash('knowledge/' + source) is None
        assert manager.storage.get_file_hash('knowledge/' + target) is None
        source = 'renamed/guide.' + extension
        target = 'renamed/target.' + extension
        assert 'Retain summary' in index.read_text(encoding='utf-8')
    elif action == 'delete':
        result = service.dispatch('delete_category', {'path': 'category', 'confirm': True})
        assert result['code'] == 200
        assert result['payload']['deleted_documents'] == 2
        assert not (workspace / 'knowledge/category').exists()
        assert manager.storage.get_file_hash('knowledge/' + source) is None
        assert not asyncio.run(manager.search('quasarorchid', min_score=0))
        print(json.dumps({'action': action, 'deleted': 2}))
    if action != 'delete':
        listing = service.dispatch('list')['payload']
        assert listing['stats']['pages'] == 2
        assert {f['name'] for category in listing['tree'] for f in category['files']} == {
            'guide.' + extension, 'target.' + extension,
        }
        index = (workspace / 'knowledge/index.md').read_text(encoding='utf-8')
        assert './' + source in index and './' + target in index
        graph = service.dispatch('graph')['payload']
        assert {node['id'] for node in graph['nodes']} == {source, target}
        assert graph['links'] == [{'source': source, 'target': target}]
        assert manager.storage.get_file_hash('knowledge/' + source) == MemoryStorage.compute_hash(content)
        assert (workspace / 'knowledge' / source).read_text(encoding='utf-8') == content
        if action != 'rename':
            keyword_paths = {item.path for item in asyncio.run(manager.search('quasarorchid', min_score=0))}
            assert keyword_paths == {'knowledge/' + source}, keyword_paths
        else:
            assert service.dispatch('read', {'path': source})['payload']['content'] == content
            assert manager.storage.get_file_hash('knowledge/' + target) == MemoryStorage.compute_hash('# Owned target\n')
        if action == 'cli':
            stats = CliRunner().invoke(knowledge, [])
            tree = CliRunner().invoke(knowledge, ['list'])
            assert stats.exit_code == tree.exit_code == 0
            assert 'Pages:  2' in stats.output
            assert 'category/ (2)' in tree.output
            assert 'guide' in tree.output and 'target' in tree.output
            assert 'guide.' + extension not in tree.output
            assert 'index' not in tree.output
        print(json.dumps({'action': action, 'source': source, 'pages': 2}))
finally:
    manager.close()
"""


@pytest.mark.parametrize('extension', ['md', 'MD', 'Md', 'mD'])
@pytest.mark.parametrize('action', ['views', 'rename', 'delete', 'cli'])
def test_admitted_extension_case_survives_knowledge_consumers(tmp_path, extension, action):
    home, data, workspace = (tmp_path / name for name in ('home', 'data', 'workspace'))
    home.mkdir()
    data.mkdir()
    (workspace / 'knowledge/category').mkdir(parents=True)
    (data / 'config.json').write_text(json.dumps({'agent_workspace': str(workspace.resolve())}), encoding='utf-8')
    env = {
        'PATH': os.environ.get('PATH', ''),
        'HOME': str(home), 'USERPROFILE': str(home), 'COW_DATA_DIR': str(data),
        'PYTHONPATH': os.pathsep.join([str(REPO), *sys.path]),
        'PYTHONDONTWRITEBYTECODE': '1',
    }
    result = subprocess.run([sys.executable, '-c', PROGRAM, str(workspace), extension, action],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1])['action'] == action
