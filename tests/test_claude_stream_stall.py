# encoding:utf-8
import json
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

THINKING = [
    {"type": "message_start", "message": {"usage": {"input_tokens": 1}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hmm"}},
]
TEXT_THEN_SILENCE = [
    {"type": "message_start", "message": {"usage": {"input_tokens": 1}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}},
]
COMPLETE = [
    {"type": "message_start", "message": {"usage": {"input_tokens": 1}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "done"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}},
    {"type": "message_stop"},
]


def _read_body(conn):
    data = b""
    while b"\r\n\r\n" not in data:
        data += conn.recv(65536)
    head, body = data.split(b"\r\n\r\n", 1)
    length = next(int(line.split(b":")[1]) for line in head.split(b"\r\n") if line.lower().startswith(b"content-length"))
    while len(body) < length:
        body += conn.recv(65536)
    return json.loads(body)


def _scripted_server(responses):
    """Serve each (events, hang) in turn: send the events, then stay silent if hang, else close."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(len(responses))
    release = threading.Event()
    bodies = []

    def serve():
        silent = []
        for events, hang in responses:
            conn, _ = srv.accept()
            bodies.append(_read_body(conn))
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                         b"Transfer-Encoding: chunked\r\n\r\n")
            for event in events:
                payload = f"data: {json.dumps(event)}\n\n".encode()
                conn.sendall(f"{len(payload):x}\r\n".encode() + payload + b"\r\n")
            if hang:
                silent.append(conn)
                continue
            conn.sendall(b"0\r\n\r\n")
            conn.close()
        release.wait(30)
        for conn in silent:
            conn.close()
        srv.close()

    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1], release, bodies


def _bot(monkeypatch, port):
    from config import conf
    from models.claudeapi import claude_api_bot
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    monkeypatch.setattr(claude_api_bot, "STREAM_STALL_SECONDS", 1.5)
    monkeypatch.setitem(conf(), "claude_api_base", f"http://127.0.0.1:{port}/v1")
    monkeypatch.setitem(conf(), "claude_api_key", "test")
    monkeypatch.setitem(conf(), "proxy", "")
    monkeypatch.setenv("NO_PROXY", "*")
    return ClaudeAPIBot.__new__(ClaudeAPIBot)


def _run(bot, params, release):
    started = time.monotonic()
    try:
        chunks = list(bot._handle_stream_response(params))
    finally:
        release.set()
    return chunks, time.monotonic() - started


def test_silent_stream_is_cut_and_reported_as_retryable(monkeypatch):
    port, release, _ = _scripted_server([(TEXT_THEN_SILENCE, True)])
    chunks, elapsed = _run(_bot(monkeypatch, port), {"model": "m", "messages": []}, release)

    assert elapsed < 10
    errors = [c for c in chunks if c.get("error")]
    assert len(errors) == 1
    assert errors[0]["status_code"] == 0
    assert "connection" in errors[0]["message"].lower()
    assert "stalled" in errors[0]["message"]


def test_stall_while_thinking_retries_with_lower_effort(monkeypatch):
    port, release, bodies = _scripted_server([(THINKING, True), (COMPLETE, False)])
    params = {"model": "m", "messages": [], "thinking": {"type": "adaptive", "display": "summarized"},
              "output_config": {"effort": "high"}}
    chunks, _ = _run(_bot(monkeypatch, port), params, release)

    assert not [c for c in chunks if c.get("error")]
    assert "done" in "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c.get("choices"))
    assert [b["output_config"]["effort"] for b in bodies] == ["high", "medium"]


def test_stall_after_visible_output_is_not_retried_inside_the_bot(monkeypatch):
    port, release, bodies = _scripted_server([(TEXT_THEN_SILENCE, True)])
    params = {"model": "m", "messages": [], "thinking": {"type": "adaptive", "display": "summarized"},
              "output_config": {"effort": "high"}}
    chunks, _ = _run(_bot(monkeypatch, port), params, release)

    assert len(bodies) == 1
    assert [c for c in chunks if c.get("error")]


def _captured_request(monkeypatch, stream):
    from config import conf
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    captured = {}
    bot = ClaudeAPIBot.__new__(ClaudeAPIBot)
    monkeypatch.setitem(conf(), "model", "claude-opus-5-5")
    monkeypatch.setitem(conf(), "character_desc", "")
    handler = "_handle_stream_response" if stream else "_handle_sync_response"
    monkeypatch.setattr(bot, handler, lambda request_params: captured.setdefault("request", request_params) or {})
    bot.call_with_tools(messages=[{"role": "user", "content": "hi"}], tools=[], stream=stream,
                        thinking={"type": "disabled"})
    return captured["request"]


def test_streaming_adaptive_model_always_asks_for_thinking_summaries(monkeypatch):
    assert _captured_request(monkeypatch, stream=True)["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert "thinking" not in _captured_request(monkeypatch, stream=False)


def test_lower_thinking_steps_down_and_stops():
    from models.claudeapi.claude_api_bot import _lower_thinking

    adaptive = {"thinking": {"type": "adaptive"}, "output_config": {"effort": "xhigh"}}
    assert _lower_thinking(adaptive)["output_config"]["effort"] == "medium"
    assert _lower_thinking({"thinking": {"type": "adaptive"}})["output_config"]["effort"] == "medium"
    assert _lower_thinking({"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}}) is None
    assert _lower_thinking({"thinking": {"type": "enabled", "budget_tokens": 8000}})["thinking"]["budget_tokens"] == 4000
    assert _lower_thinking({"thinking": {"type": "enabled", "budget_tokens": 1024}}) is None
    assert _lower_thinking({"model": "m"}) is None
