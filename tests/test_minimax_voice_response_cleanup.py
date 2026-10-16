import pytest
from bridge.reply import ReplyType
from voice.minimax import minimax_voice as module

class Response:
    headers = {}
    status_code = 200
    def __init__(self, mode):
        self.mode = mode
        self.closed = 0
    def close(self):
        self.closed += 1
    def raise_for_status(self):
        if self.mode == 'status':
            raise RuntimeError('HTTP failure')
    def iter_lines(self):
        if self.mode == 'iterator':
            raise RuntimeError('broken stream')
        if self.mode == 'success':
            yield b'data:{"data":{"audio":"616263"}}'

@pytest.mark.parametrize('mode', ['success', 'empty', 'status', 'iterator', 'oversize'])
def test_synthesis_response_closes_on_every_exit(tmp_path, monkeypatch, mode):
    response = Response('success' if mode == 'oversize' else mode)
    monkeypatch.setattr(module, 'conf', lambda: {})
    monkeypatch.setattr(module.requests, 'post', lambda *a, **kw: response)
    monkeypatch.setattr(module.TmpDir, 'path', lambda self: str(tmp_path) + '/')
    if mode == 'oversize':
        monkeypatch.setattr(module, 'MAX_FILE_BYTES', 2)
    reply = module.MinimaxVoice().textToVoice('hello')
    assert reply.type == (ReplyType.VOICE if mode == 'success' else ReplyType.ERROR)
    assert response.closed == 1
