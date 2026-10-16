import importlib.util
from pathlib import Path
import pytest
from bridge.reply import ReplyType

# Reuse the suite's optional-provider doubles; no codec or network is invoked.
spec = importlib.util.spec_from_file_location('google_error_test_support', Path(__file__).with_name('test_google_voice_errors.py'))
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)
from voice.google import google_voice as module

@pytest.mark.parametrize('phase', ['open', 'record'])
def test_audio_loading_failure_returns_error(monkeypatch, phase):
    if phase == 'open':
        def open_audio(path):
            raise FileNotFoundError(path)
        monkeypatch.setattr(module.speech_recognition, 'AudioFile', open_audio)
    else:
        def record(source):
            raise ValueError('corrupt WAV')
        monkeypatch.setattr(module.GoogleVoice.recognizer, 'record', record)
    assert module.GoogleVoice().voiceToText('missing.wav').type == ReplyType.ERROR
