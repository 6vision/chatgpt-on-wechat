"""Reading an MCP SSE response has a total deadline; keepalives do not reset it."""

import time

import pytest

from agent.tools.mcp.mcp_client import McpClient


def _keepalives(limit=300):
    for _ in range(limit):  # ~3s, well past the 1s budget
        time.sleep(0.01)
        yield b": keepalive\n"
    raise AssertionError("SSE read never hit its total deadline")


def _client():
    return McpClient({"name": "test", "type": "streamable-http", "url": "http://mcp.test", "timeout": 1})


def test_keepalive_only_stream_times_out():
    with pytest.raises(TimeoutError, match="timed out after 1s"):
        _client()._read_sse_response(_keepalives(), 7)


def test_response_after_keepalives_is_returned():
    stream = [b": keepalive\n"] * 5 + [b'data: {"jsonrpc": "2.0", "id": 7, "result": "ok"}\n', b"\n"]
    assert _client()._read_sse_response(iter(stream), 7)["result"] == "ok"
