import importlib
import importlib.util
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import pytest
from bridge.reply import ReplyType

@pytest.mark.parametrize('provider', ['google', 'edge', 'pytts'])
def test_identical_replies_have_independent_output_files(tmp_path, monkeypatch, provider):
    if provider in ('google', 'pytts'):
        filename = 'test_google_voice_errors.py' if provider == 'google' else 'test_pytts_voice_timeout.py'
        spec = importlib.util.spec_from_file_location('voice_' + provider + '_support', Path(__file__).with_name(filename))
        support = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(support)
    else:
        monkeypatch.setitem(sys.modules, 'edge_tts', SimpleNamespace())
    module = importlib.import_module('voice.' + provider + '.' + provider + '_voice')
    monkeypatch.setattr(time, 'time', lambda: 1000)
    monkeypatch.setattr(module.TmpDir, 'path', lambda self: str(tmp_path) + '/')
    if provider == 'google':
        monkeypatch.setattr(module, 'gTTS', lambda **kw: SimpleNamespace(save=lambda path: Path(path).write_bytes(b'audio')))
        voice = module.GoogleVoice()
    elif provider == 'edge':
        voice = module.EdgeVoice()
        async def generate(text, path):
            Path(path).write_bytes(b'audio')
        monkeypatch.setattr(voice, 'gen_voice', generate)
    else:
        voice = module.PyttsVoice()
        engine = support._FakeEngine()
        engine.save_to_file = lambda text, path: Path(path).write_bytes(b'audio')
        voice.engine = engine
    first = voice.textToVoice('same reply')
    Path(first.content).write_bytes(b'first-clip-sentinel')
    second = voice.textToVoice('same reply')
    assert first.type == second.type == ReplyType.VOICE
    assert first.content != second.content
    assert Path(first.content).read_bytes() == b'first-clip-sentinel'
