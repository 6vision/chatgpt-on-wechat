"""Public mutations and legacy upgrades keep both FTS indexes consistent."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[1]
LEGACY_TRIGGERS = {'chunks_ad': 'CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN\n                DELETE FROM chunks_fts WHERE rowid = old.rowid;\n            END', 'chunks_au': 'CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN\n                UPDATE chunks_fts SET text = new.text, id = new.id,\n                                     user_id = new.user_id, path = new.path,\n                                     source = new.source, scope = new.scope\n                WHERE rowid = new.rowid;\n            END', 'chunks_trigram_ad': 'CREATE TRIGGER chunks_trigram_ad\n            AFTER DELETE ON chunks BEGIN\n                DELETE FROM chunks_fts_trigram WHERE rowid = old.rowid;\n            END'}
PROGRAM = r"""
import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path
from agent.knowledge.service import KnowledgeService
from agent.memory.config import MemoryConfig
from agent.memory.manager import MemoryManager
from agent.memory.storage import MemoryChunk, MemoryStorage
from agent.memory import storage as storage_module
from agent.memory.conversation_store import ConversationStore

workspace = Path(sys.argv[1]).resolve()
language, action = sys.argv[2:4]
legacy = json.loads(sys.argv[4])
word, replacement = ('quasarorchid', 'papyrusalmanac') if language == 'unicode' else ('紫羅蘭星辰', '青木翠谷')
config = MemoryConfig(workspace_root=str(workspace))
manager = None

def wait(storage):
    deadline = time.monotonic() + 10
    while str(storage.db_path) in storage_module._maintenance_running:
        assert time.monotonic() < deadline, 'owned maintenance did not finish'
        time.sleep(.01)

def integrity(storage):
    for table in ('chunks_fts', 'chunks_fts_trigram'):
        if table.endswith('trigram') and not storage.trigram_fts5_available:
            continue
        storage.conn.execute('INSERT INTO ' + table + '(' + table + ',rank) VALUES(\'integrity-check\',1)')
        storage.conn.commit()

def rows(storage):
    return {
        'chunks': [tuple(row) for row in storage.conn.execute('SELECT * FROM chunks ORDER BY rowid')],
        'files': [tuple(row) for row in storage.conn.execute('SELECT * FROM files ORDER BY path')],
    }

def seed(storage):
    for name, sql in legacy.items():
        storage.conn.execute('DROP TRIGGER ' + name)
        storage.conn.execute(sql)
    storage.conn.commit()

try:
    if action == 'fallback':
        # A controlled capability boundary: SQLite itself raises the tokenizer
        # error. This does not claim an older SQLite runtime was installed.
        def unavailable(conn):
            conn.execute("CREATE VIRTUAL TABLE owned_unavailable USING fts5(text, tokenize='owned_missing_tokenizer')")
        MemoryStorage._create_trigram_objects = staticmethod(unavailable)
    manager = MemoryManager(config, embedding_provider=None)
    wait(manager.storage)
    service = KnowledgeService(str(workspace), manager)
    def dispatch(action, payload):
        result = service.dispatch(action, payload)
        assert result['code'] == 200, result
        return result['payload']
    def search(query):
        return asyncio.run(manager.search(query, min_score=0))
    def paths(query):
        return {item.path for item in search(query)}

    if action == 'update':
        chunk = MemoryChunk(id='owned', user_id=None, scope='shared', source='memory',
                            path='owned.md', start_line=1, end_line=1,
                            text=word, embedding=None, hash=MemoryStorage.compute_hash(word))
        manager.storage.save_chunk(chunk)
        assert [r.path for r in manager.storage.search_keyword(word)] == ['owned.md']
        chunk.text = replacement
        chunk.hash = MemoryStorage.compute_hash(replacement)
        manager.storage.save_chunk(chunk)
        assert manager.storage.search_keyword(word) == []
        assert [r.path for r in manager.storage.search_keyword(replacement)] == ['owned.md']
        integrity(manager.storage)
    else:
        if action == 'legacy':
            conversation = ConversationStore(manager.storage.db_path)
            conversation.append_messages('owned-session', [{'role':'user', 'content':'owned history'}], channel_type='web')
            seed(manager.storage)
            manager.close()
            manager = MemoryManager(config, embedding_provider=None)
            wait(manager.storage)
            service = KnowledgeService(str(workspace), manager)
            triggers = ' '.join(sql for (sql,) in manager.storage.conn.execute("SELECT sql FROM sqlite_master WHERE type='trigger'"))
            assert all(sql not in triggers for sql in legacy.values()), 'legacy triggers survived the reopen'
            assert not manager.storage.conn.execute("SELECT 1 FROM _meta WHERE key='fts_rebuild_pending'").fetchone()
        dispatch('create_document', {'path': 'category/guide.md', 'content': '# Owned guide\n\n' + word + ' reference\n'})
        dispatch('create_document', {'path': 'category/target.md', 'content': '# Owned target\n\nordinary target\n'})
        assert paths(word) == {'knowledge/category/guide.md'}
        assert service.dispatch('delete_documents', {'paths': ['index.md']})['code'] == 403
        if action in ('rename', 'legacy'):
            moved = dispatch('rename_category', {'path':'category', 'new_path':'renamed'})
            assert moved['moved_documents'] == 2
            expected = {'knowledge/renamed/guide.md'}
        elif action == 'overwrite':
            dispatch('create_document', {'path':'category/guide.md', 'content':'# Owned guide\n\n' + replacement + ' reference\n', 'overwrite':True})
            expected = set()
            assert paths(replacement) == {'knowledge/category/guide.md'}
        elif action == 'delete-reuse':
            dispatch('delete_documents', {'paths':['category/guide.md', 'category/target.md']})
            dispatch('create_document', {'path':'category/fresh.md', 'content':'# Owned fresh\n\nordinary fresh\n'})
            expected = set()
        else:
            expected = {'knowledge/category/guide.md'}
        before_reopen = rows(manager.storage)
        assert paths(word) == expected
        integrity(manager.storage)
        manager.close()
        manager = MemoryManager(config, embedding_provider=None)
        wait(manager.storage)
        assert rows(manager.storage) == before_reopen
        assert paths(word) == expected
        assert all(word in item.snippet for item in search(word))
        integrity(manager.storage)
        if action == 'legacy':
            assert conversation.load_messages('owned-session')[0]['content'] == 'owned history'
        if action == 'fallback':
            assert not manager.storage.trigram_fts5_available
    print(json.dumps({'language':language, 'action':action, 'passed':True}))
finally:
    if manager is not None:
        wait(manager.storage)
        manager.close()
"""


@pytest.mark.parametrize('language,action', [
    (language, action) for language in ('unicode', 'trigram')
    for action in ('control', 'rename', 'overwrite', 'delete-reuse', 'legacy', 'update')
] + [('trigram', 'fallback')])
def test_public_mutations_and_legacy_upgrade_preserve_fts(tmp_path, language, action):
    home, data, workspace = (tmp_path / name for name in ('home', 'data', 'workspace'))
    home.mkdir()
    data.mkdir()
    (workspace / 'knowledge/category').mkdir(parents=True)
    (data / 'config.json').write_text('{}', encoding='utf-8')
    env = {
        'PATH': os.environ.get('PATH', ''),
        'HOME': str(home), 'USERPROFILE': str(home), 'COW_DATA_DIR': str(data),
        'PYTHONPATH': os.pathsep.join([str(REPO), *sys.path]),
        'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
    }
    child = subprocess.run([sys.executable, '-c', PROGRAM, str(workspace), language, action,
                            json.dumps(LEGACY_TRIGGERS)], cwd=tmp_path, env=env,
                           capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stdout + child.stderr
    assert json.loads(child.stdout.splitlines()[-1])['passed']
