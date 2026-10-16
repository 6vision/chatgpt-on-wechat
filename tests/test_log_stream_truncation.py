import json
from channel.web.api import logs

def test_live_stream_recovers_after_log_is_truncated(tmp_path, monkeypatch):
    path = tmp_path / 'run.log'
    path.write_text('previous log entry ' * 20 + '\n')
    monkeypatch.setattr(logs, '_require_auth', lambda: None)
    monkeypatch.setattr(logs, 'get_data_root', lambda: str(tmp_path))
    monkeypatch.setattr(logs.web, 'header', lambda *args: None)
    stream = logs.LogsHandler().GET()
    try:
        assert json.loads(next(stream).decode()[6:])['type'] == 'init'
        path.write_text('fresh log\n')
        chunk = next(stream)
        assert chunk.startswith(b'data: '), chunk
        assert json.loads(chunk.decode()[6:]) == {'type': 'line', 'content': 'fresh log\n'}
        with path.open('a') as output:
            output.write('following log\n')
        assert json.loads(next(stream).decode()[6:])['content'] == 'following log\n'
    finally:
        stream.close()
