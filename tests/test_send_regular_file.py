import os
import pytest
from agent.tools.send.send import Send


def test_send_refuses_directory(tmp_path):
    result = Send({'cwd': str(tmp_path)}).execute({'path': '.'})
    assert result.status == 'error'
    assert 'file' in str(result.result).lower()


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='FIFO unavailable')
def test_send_refuses_fifo_without_opening(tmp_path):
    path = tmp_path / 'pipe.txt'
    os.mkfifo(path)
    result = Send({'cwd': str(tmp_path)}).execute({'path': str(path)})
    assert result.status == 'error'


def test_send_accepts_regular_file(tmp_path):
    path = tmp_path / 'note.txt'
    path.write_text('hello')
    result = Send({'cwd': str(tmp_path)}).execute({'path': 'note.txt'})
    assert result.status == 'success'
    assert result.result['size'] == 5
