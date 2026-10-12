# encoding:utf-8
"""A stdio MCP server whose handshake fails is shut down instead of left running."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.mcp import mcp_client as mcp_client_module
from agent.tools.mcp.mcp_client import McpClient


def _boot(stdout_lines):
    client = McpClient({"name": "srv", "type": "stdio", "command": "node"})
    proc = MagicMock()
    proc.stdout = iter(stdout_lines)
    proc.stderr = iter([])
    with patch.object(mcp_client_module.subprocess, "Popen", return_value=proc):
        ok = client.initialize()
    return client, proc, ok


@pytest.mark.parametrize("stdout_lines", [
    [],  # exits without answering
    ['{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"no"}}\n'],
])
def test_failed_handshake_terminates_child(stdout_lines):
    client, proc, ok = _boot(stdout_lines)
    assert ok is False
    assert client._proc is None
    proc.terminate.assert_called_once()


def test_successful_handshake_keeps_child():
    client, proc, ok = _boot(['{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05"}}\n'])
    assert ok is True
    assert client._proc is proc
    proc.terminate.assert_not_called()
