from types import SimpleNamespace
import pytest
from agent.tools.vision.vision import Vision, VisionProvider, VisionAPIError
from agent.tools.vision import vision as module


@pytest.mark.parametrize('payload', [{'choices': []}, {'usage': {}}, {'choices': [{'message': {'content': ''}}]}, {'choices': [{'message': {'content': '   '}}]}])
def test_empty_http_completion_does_not_claim_success(monkeypatch, payload):
    monkeypatch.setattr(module.requests, 'post', lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: payload))
    with pytest.raises(VisionAPIError):
        Vision()._call_api(VisionProvider('test', 'fake-key', 'https://example.invalid/v1'), 'fake-model', 'Question', {})


def test_empty_provider_completion_falls_back_to_valid_answer(monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append(url)
        payload = {'choices': []} if len(calls) == 1 else {'choices': [{'message': {'content': 'Valid test answer'}}]}
        return SimpleNamespace(status_code=200, json=lambda: payload)
    monkeypatch.setattr(module.requests, 'post', post)
    providers = [VisionProvider(name, 'fake-key', f'https://{name}.invalid/v1') for name in ['first', 'second']]
    result = Vision()._call_with_fallback(providers, 'fake-model', 'Question', {})
    assert result.status == 'success'
    assert result.result['provider'] == 'second'
    assert result.result['content'] == 'Valid test answer'
    assert len(calls) == 2
