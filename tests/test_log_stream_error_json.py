import json
from channel.web.api import logs

def test_initial_tail_failure_is_a_valid_json_event(tmp_path, monkeypatch):
    (tmp_path / 'run.log').write_text('old log\n')
    monkeypatch.setattr(logs, '_require_auth', lambda: None)
    monkeypatch.setattr(logs, 'get_data_root', lambda: str(tmp_path))
    monkeypatch.setattr(logs.web, 'header', lambda *args: None)
    message = 'Cannot read "path\\file"\nretry later'
    def fail(*args, **kwargs):
        raise OSError(message)
    monkeypatch.setattr(logs, 'tail_lines', fail)
    stream = logs.LogsHandler().GET()
    try:
        event = json.loads(next(stream).decode()[6:])
        assert event == {'type': 'error', 'message': message}
    finally:
        stream.close()
