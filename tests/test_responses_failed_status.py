from unittest.mock import Mock
from models.openai.responses_adapter import responses_to_chat_completion
from models.openai_compatible_bot import OpenAICompatibleBot


def test_failed_response_retains_provider_message():
    result = responses_to_chat_completion(
        {"status": "failed", "error": {"code": "server_error", "message": "Generation failed"}, "output": []}
    )
    assert result["error"]
    assert result["message"] == "Generation failed"
    assert "choices" not in result


def test_failed_response_without_details_has_fallback():
    result = responses_to_chat_completion({"status": "failed", "output": []})
    assert result["error"]
    assert result["message"] == "Responses request failed"


def test_bot_surfaces_provider_failure_from_http_success(monkeypatch):
    bot = OpenAICompatibleBot.__new__(OpenAICompatibleBot)
    client = Mock()
    client.responses.return_value = {"status": "failed", "error": {"message": "Generation failed"}}
    monkeypatch.setattr(bot, "_get_http_client", lambda: client)
    result = bot._handle_responses_sync({}, "test", "https://test.invalid", None)
    assert result["error"]
    assert result["message"] == "Generation failed"


def test_successful_response_retains_text():
    result = responses_to_chat_completion(
        {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "hello"}]}]}
    )
    assert result["choices"][0]["message"]["content"] == "hello"
