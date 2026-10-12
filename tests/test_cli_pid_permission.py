import pytest
from cli.commands import process

@pytest.mark.parametrize('error, expected', [(PermissionError(), True), (ProcessLookupError(), False)])
def test_posix_process_existence(monkeypatch, error, expected):
    monkeypatch.setattr(process, '_IS_WIN', False)
    def kill(pid, sig):
        assert (pid, sig) == (1234, 0)
        raise error
    monkeypatch.setattr(process.os, 'kill', kill)
    assert process._is_pid_alive(1234) is expected

def test_permission_denied_preserves_pid_file(tmp_path, monkeypatch):
    monkeypatch.setattr(process, '_IS_WIN', False)
    monkeypatch.setattr(process, 'get_project_root', lambda: str(tmp_path))
    (tmp_path / '.cow.pid').write_text('1234')
    def kill(pid, sig):
        raise PermissionError()
    monkeypatch.setattr(process.os, 'kill', kill)
    assert process._read_pid() == 1234
    assert (tmp_path / '.cow.pid').read_text() == '1234'
