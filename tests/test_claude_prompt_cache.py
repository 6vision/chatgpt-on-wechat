# encoding:utf-8
import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TOOLS = [{"name": "ls", "description": "List a directory",
          "input_schema": {"type": "object", "properties": {}}}]

LOOP_MESSAGES = [
    {"role": "user", "content": "list the files"},
    {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1", "name": "ls", "input": {}}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "a.txt"}]},
]


def _capture(monkeypatch, model="claude-opus-5-5", cache_ttl="1h"):
    from config import conf
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    captured = {}
    bot = ClaudeAPIBot.__new__(ClaudeAPIBot)
    monkeypatch.setitem(conf(), "model", model)
    monkeypatch.setitem(conf(), "character_desc", "")
    monkeypatch.setitem(conf(), "claude_cache_ttl", cache_ttl)
    monkeypatch.setattr(bot, "_handle_sync_response",
                        lambda request_params: captured.setdefault("request", request_params) or {"content": "ok"})
    return bot, captured


def test_agent_request_marks_system_and_last_block(monkeypatch):
    bot, captured = _capture(monkeypatch)
    messages = [{"role": "system", "content": "You are an agent."}] + copy.deepcopy(LOOP_MESSAGES)
    snapshot = copy.deepcopy(messages)

    bot.call_with_tools(messages=messages, tools=TOOLS, stream=False)

    request = captured["request"]
    assert request["system"] == [{"type": "text", "text": "You are an agent.",
                                  "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    assert request["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in blk
               for msg in request["messages"][:-1] if isinstance(msg["content"], list)
               for blk in msg["content"])
    # The agent's history is shared across turns and must not pick up markers.
    assert messages == snapshot


def test_5m_ttl_config_keeps_the_system_on_the_default_ttl(monkeypatch):
    bot, captured = _capture(monkeypatch, cache_ttl="5m")

    bot.call_with_tools(messages=[{"role": "system", "content": "sys"},
                                  {"role": "user", "content": "hi"}], tools=TOOLS, stream=False)

    assert captured["request"]["system"][-1]["cache_control"] == {"type": "ephemeral"}


def test_earlier_5m_breakpoint_prevents_a_1h_system_breakpoint():
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    tools = [dict(TOOLS[0], cache_control={"type": "ephemeral"})]

    new_system, _ = ClaudeAPIBot._apply_prompt_cache("sys", copy.deepcopy(LOOP_MESSAGES), tools,
                                                     system_ttl="1h")

    assert new_system[-1]["cache_control"] == {"type": "ephemeral"}


def test_request_without_tools_is_not_cached(monkeypatch):
    bot, captured = _capture(monkeypatch)

    bot.call_with_tools(messages=[{"role": "system", "content": "sys"},
                                  {"role": "user", "content": "hi"}], tools=None, stream=False)

    request = captured["request"]
    assert request["system"] == "sys"
    assert request["messages"] == [{"role": "user", "content": "hi"}]


def test_string_user_message_is_wrapped_into_a_marked_block(monkeypatch):
    bot, captured = _capture(monkeypatch)

    bot.call_with_tools(messages=[{"role": "user", "content": "hi"}], tools=TOOLS, stream=False)

    request = captured["request"]
    assert "system" not in request
    assert request["messages"] == [{"role": "user", "content": [
        {"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}]}]


def test_existing_breakpoints_count_against_the_limit():
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    marked = {"type": "ephemeral"}
    system = [{"type": "text", "text": f"part {i}", "cache_control": marked} for i in range(3)]
    system.append({"type": "text", "text": "tail"})
    messages = copy.deepcopy(LOOP_MESSAGES)

    new_system, new_messages = ClaudeAPIBot._apply_prompt_cache(system, messages, TOOLS)

    assert new_system[-1]["cache_control"] == marked
    assert "cache_control" not in new_messages[-1]["content"][-1]


def test_thinking_block_is_never_marked():
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    messages = [{"role": "user", "content": "hi"},
                {"role": "assistant", "content": [{"type": "thinking", "thinking": "x", "signature": "s"}]}]

    _, new_messages = ClaudeAPIBot._apply_prompt_cache(None, messages, TOOLS)

    assert new_messages == messages


def test_sync_usage_reports_the_whole_prompt(monkeypatch):
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    bot = ClaudeAPIBot.__new__(ClaudeAPIBot)
    monkeypatch.setattr(type(bot), "api_key", property(lambda self: "k"))
    monkeypatch.setattr(type(bot), "api_base", property(lambda self: "https://example.invalid/v1"))
    monkeypatch.setattr(type(bot), "proxy", property(lambda self: None))

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "msg_1", "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 2, "output_tokens": 5,
                              "cache_creation_input_tokens": 600, "cache_read_input_tokens": 17000}}

    monkeypatch.setattr("requests.post", lambda *a, **kw: _Resp())

    usage = bot._handle_sync_response({"model": "claude-opus-5-5"})["usage"]

    assert usage["prompt_tokens"] == 17602
    assert usage["total_tokens"] == 17607
    assert usage["cache_read_input_tokens"] == 17000


def test_stream_usage_reports_the_whole_prompt(monkeypatch):
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    bot = ClaudeAPIBot.__new__(ClaudeAPIBot)
    monkeypatch.setattr(type(bot), "api_key", property(lambda self: "k"))
    monkeypatch.setattr(type(bot), "api_base", property(lambda self: "https://example.invalid/v1"))
    monkeypatch.setattr(type(bot), "proxy", property(lambda self: None))

    events = [
        {"type": "message_start", "message": {"usage": {
            "input_tokens": 2, "output_tokens": 1,
            "cache_creation_input_tokens": 600, "cache_read_input_tokens": 17000}}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ]

    class _Resp:
        status_code = 200

        @staticmethod
        def iter_lines():
            for event in events:
                yield ("data: " + json.dumps(event)).encode("utf-8")

    monkeypatch.setattr("requests.post", lambda *a, **kw: _Resp())

    chunks = list(bot._handle_stream_response({"model": "claude-opus-5-5"}))
    usage = [c["usage"] for c in chunks if c.get("usage")][-1]

    assert usage["prompt_tokens"] == 17602
    assert usage["completion_tokens"] == 5
    assert usage["cache_read_input_tokens"] == 17000
