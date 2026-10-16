from unittest.mock import Mock
import pytest
from models.minimax.minimax_bot import MinimaxBot


@pytest.mark.parametrize("mode", ["success", "http_error", "early_close", "read_error"])
def test_stream_response_closed(monkeypatch, mode):
    bot = MinimaxBot.__new__(MinimaxBot)
    monkeypatch.setattr(
        "models.minimax.minimax_bot.conf",
        lambda: {"minimax_api_key": "test", "minimax_api_base": "https://test.invalid"},
    )
    response = Mock(status_code=500 if mode == "http_error" else 200, text="failed")
    response.iter_content.return_value = iter([b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'])
    response.iter_lines.return_value = iter([b'data: {"choices":[{"delta":{"content":"hi"}}]}', b"data: [DONE]"])
    if mode == "read_error":
        response.iter_lines.side_effect = RuntimeError("broken read")
        response.iter_content.side_effect = RuntimeError("broken read")
    monkeypatch.setattr("models.minimax.minimax_bot.requests.post", Mock(return_value=response))
    stream = bot._handle_stream_response({})
    if mode == "early_close":
        next(stream)
        stream.close()
    else:
        list(stream)
    response.close.assert_called_once()
