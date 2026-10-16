import json
import pytest
from cli.utils import load_config_json

@pytest.mark.parametrize('value', [None, [], ['terminal'], 'text', 42, True])
def test_non_object_config_returns_empty_mapping(tmp_path, monkeypatch, value):
    monkeypatch.setenv('COW_DATA_DIR', str(tmp_path))
    (tmp_path / 'config.json').write_text(json.dumps(value))
    assert load_config_json() == {}

def test_object_config_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv('COW_DATA_DIR', str(tmp_path))
    (tmp_path / 'config.json').write_text('{"channel_type":"terminal"}')
    assert load_config_json() == {'channel_type': 'terminal'}
