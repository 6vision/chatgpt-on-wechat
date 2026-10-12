# encoding:utf-8
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

WRITE_TOOL = {
    "name": "write",
    "description": "Write a file",
    "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
}


def _bot(monkeypatch, captured, stream):
    from config import conf
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    bot = ClaudeAPIBot.__new__(ClaudeAPIBot)
    monkeypatch.setitem(conf(), "model", "claude-opus-5-5")
    monkeypatch.setitem(conf(), "character_desc", "")
    handler = "_handle_stream_response" if stream else "_handle_sync_response"
    monkeypatch.setattr(bot, handler, lambda request_params: captured.setdefault("request", request_params) or {})
    return bot


def test_streaming_tool_call_enables_eager_input_streaming(monkeypatch):
    captured = {}
    server_tool = {"type": "web_search_20250305", "name": "web_search"}
    tools = [dict(WRITE_TOOL), server_tool]
    _bot(monkeypatch, captured, stream=True).call_with_tools(
        messages=[{"role": "user", "content": "hi"}], tools=tools, stream=True)

    sent = captured["request"]["tools"]
    assert sent[0]["eager_input_streaming"] is True
    assert "eager_input_streaming" not in sent[1]
    assert "eager_input_streaming" not in tools[0]


def test_sync_tool_call_leaves_tools_untouched(monkeypatch):
    captured = {}
    _bot(monkeypatch, captured, stream=False).call_with_tools(
        messages=[{"role": "user", "content": "hi"}], tools=[dict(WRITE_TOOL)], stream=False)

    assert "eager_input_streaming" not in captured["request"]["tools"][0]
