"""The runtime reads mcp.json the same way the console does."""

import json
import os

import pytest

from agent.tools.mcp import service
from agent.tools.tool_manager import ToolManager


def _runtime_names(workspace):
    manager = ToolManager.__new__(ToolManager)
    manager.workspace_root = workspace
    return {s["name"] for s in manager._load_mcp_configs()}


@pytest.mark.parametrize("payload, expected", [
    ({"mcpServers": {}}, set()),
    ({"mcp_servers": {}}, set()),
    ({}, set()),
    ({"demo": {"command": "npx", "args": []}}, {"demo"}),
    ({"mcpServers": {"demo": {"command": "npx", "args": []}}}, {"demo"}),
])
def test_runtime_reader(tmp_path, payload, expected):
    path = service.mcp_config_path(str(tmp_path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    assert _runtime_names(str(tmp_path)) == expected


def test_editor_output_with_no_servers(tmp_path):
    service.save_servers(str(tmp_path), [])
    assert _runtime_names(str(tmp_path)) == set()
    assert service.load_servers(str(tmp_path)) == []
