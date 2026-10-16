import importlib
from unittest.mock import Mock
import pytest

PROVIDERS = [
    ("deepseek", "deepseek_bot", "DeepSeekBot"),
    ("mimo", "mimo_bot", "MimoBot"),
    ("moonshot", "moonshot_bot", "MoonshotBot"),
    ("doubao", "doubao_bot", "DoubaoBot"),
]


def prepare(monkeypatch, provider, module, clsname, response):
    source = importlib.import_module(f"models.{provider}.{module}")
    cls = getattr(source, clsname)
    bot = cls.__new__(cls)
    bot.args = {}
    monkeypatch.setattr(source, "conf", lambda: {})
    monkeypatch.setattr(source.requests, "post", Mock(return_value=response))
    return bot


@pytest.mark.parametrize("provider,module,clsname", PROVIDERS)
@pytest.mark.parametrize("mode", ["success", "http_error", "early_close", "read_error"])
def test_native_stream_response_lifecycle(monkeypatch, provider, module, clsname, mode):
    response = Mock(status_code=500 if mode == "http_error" else 200, text="failed")
    wire = b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\ndata: [DONE]\n\n'
    response.iter_lines.return_value = iter(wire.splitlines())
    response.iter_content.return_value = iter([wire])
    if mode == "read_error":
        response.iter_lines.side_effect = RuntimeError("broken read")
        response.iter_content.side_effect = RuntimeError("broken read")
    bot = prepare(monkeypatch, provider, module, clsname, response)
    stream = bot._handle_stream_response({})
    if mode == "early_close":
        next(stream)
        stream.close()
    else:
        list(stream)
    response.close.assert_called_once()
