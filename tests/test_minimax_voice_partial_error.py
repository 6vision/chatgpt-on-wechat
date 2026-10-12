from types import SimpleNamespace
from bridge.reply import ReplyType
from voice.minimax import minimax_voice as module

def test_provider_error_after_audio_does_not_publish_partial_clip(tmp_path, monkeypatch):
    lines = [b'data:{"data":{"audio":"616263"},"base_resp":{"status_code":0}}',
             b'data:{"base_resp":{"status_code":1000,"status_msg":"synthesis failed"}}']
    response = SimpleNamespace(status_code=200, headers={}, raise_for_status=lambda: None,
                               iter_lines=lambda: iter(lines), close=lambda: None)
    monkeypatch.setattr(module, 'conf', lambda: {})
    monkeypatch.setattr(module.requests, 'post', lambda *args, **kwargs: response)
    monkeypatch.setattr(module.TmpDir, 'path', lambda self: str(tmp_path) + '/')
    reply = module.MinimaxVoice().textToVoice('hello')
    assert reply.type == ReplyType.ERROR
    assert list(tmp_path.iterdir()) == []

def test_successful_audio_is_still_published(tmp_path, monkeypatch):
    response = SimpleNamespace(status_code=200, headers={}, raise_for_status=lambda: None,
                               iter_lines=lambda: iter([b'data:{"data":{"audio":"616263"},"base_resp":{"status_code":0}}']), close=lambda: None)
    monkeypatch.setattr(module, 'conf', lambda: {})
    monkeypatch.setattr(module.requests, 'post', lambda *args, **kwargs: response)
    monkeypatch.setattr(module.TmpDir, 'path', lambda self: str(tmp_path) + '/')
    reply = module.MinimaxVoice().textToVoice('hello')
    assert reply.type == ReplyType.VOICE
    from pathlib import Path
    assert Path(reply.content).read_bytes() == b'abc'
