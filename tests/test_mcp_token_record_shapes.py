import json
import pytest
from agent.tools.mcp import mcp_oauth as oauth


@pytest.mark.parametrize('value', [None, 42, 'invalid', ['bad']])
def test_malformed_server_token_record_is_isolated(tmp_path, monkeypatch, value):
    path = tmp_path / 'tokens.json'
    path.write_text(json.dumps({'bad': value, 'healthy': {'access_token': 'fake-test-token'}}))
    monkeypatch.setattr(oauth, '_store_path', lambda: str(path))
    assert oauth.load_server_record('bad') == {}
    assert oauth.load_server_record('healthy') == {'access_token': 'fake-test-token'}
    assert json.loads(path.read_text())['bad'] == value


def test_loaded_server_record_is_a_copy(tmp_path, monkeypatch):
    path = tmp_path / 'tokens.json'
    path.write_text('{"test":{"expires_at":42}}')
    monkeypatch.setattr(oauth, '_store_path', lambda: str(path))
    record = oauth.load_server_record('test')
    record['expires_at'] = 0
    assert oauth.load_server_record('test')['expires_at'] == 42
