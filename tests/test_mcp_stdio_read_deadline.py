# encoding:utf-8
"""A stdio MCP request has one total deadline; skipped notifications do not reset it."""

import json
import os
import sys
import time
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.mcp.mcp_client import McpClient

_NOTIFICATION = json.dumps({"jsonrpc": "2.0", "method": "notifications/message"}) + "\n"


class _ChattyQueue:
    """Returns a notification on every get(); `reply` is returned after `notes` of them."""

    def __init__(self, notes=None, reply=None):
        self.notes, self.reply, self.calls = notes, reply, 0

    def get(self, timeout=None):
        self.calls += 1
        if self.notes is not None and self.calls > self.notes:
            return self.reply
        if self.calls > 300:  # ~3s, well past the 1s budget
            raise AssertionError("stdio read never hit its total deadline")
        time.sleep(0.01)
        return _NOTIFICATION


def _client(queue):
    client = McpClient({"name": "chatty", "type": "stdio", "command": "node", "timeout": 1})
    client._proc = MagicMock()
    client._read_queue = queue
    return client


def test_chatty_server_that_never_answers_times_out():
    client = _client(_ChattyQueue())
    with pytest.raises(TimeoutError, match="chatty"):
        client._stdio_send({"jsonrpc": "2.0", "id": 1, "method": "tools/call"})


def test_response_after_notifications_is_returned():
    reply = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "pong"}) + "\n"
    client = _client(_ChattyQueue(notes=5, reply=reply))
    assert client._stdio_send({"jsonrpc": "2.0", "id": 1, "method": "ping"})["result"] == "pong"
