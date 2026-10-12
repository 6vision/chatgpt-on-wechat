"""Every HTTP response from a streaming request must release its connection."""
from unittest.mock import Mock

import pytest

from models.openai.openai_http_client import OpenAIHTTPClient


@pytest.mark.parametrize("status", [401, 429, 503])
def test_failed_stream_closes_response_before_return(monkeypatch, status):
    response = Mock(status_code=status)
    response.json.return_value = {"error": {"message": "try later", "code": "limited"}}
    monkeypatch.setattr("models.openai.openai_http_client.requests.post", lambda *a, **k: response)
    chunks = list(OpenAIHTTPClient().chat_completions(model="test", stream=True))
    assert chunks[0]["status_code"] == status
    assert chunks[0]["error"]["code"] == "limited"
    response.close.assert_called_once()


def test_closing_error_generator_releases_response(monkeypatch):
    response = Mock(status_code=429)
    response.json.return_value = {"error": "limited"}
    monkeypatch.setattr("models.openai.openai_http_client.requests.post", lambda *a, **k: response)
    stream = OpenAIHTTPClient().chat_completions(model="test", stream=True)
    assert next(stream)["status_code"] == 429
    stream.close()
    response.close.assert_called_once()


def test_successful_stream_still_closes_response(monkeypatch):
    response = Mock(status_code=200)
    response.iter_content.return_value = iter([b'data: {"choices": []}\n\ndata: [DONE]\n\n'])
    monkeypatch.setattr("models.openai.openai_http_client.requests.post", lambda *a, **k: response)
    assert list(OpenAIHTTPClient().chat_completions(model="test", stream=True)) == [{"choices": []}]
    response.close.assert_called_once()
