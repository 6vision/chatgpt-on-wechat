"""McpClient against a real stdio server: paginated discovery and call results."""
import json
import sys
from contextlib import contextmanager

import pytest

from agent.tools.mcp.mcp_client import McpClient
from agent.tools.mcp.mcp_tool import McpTool

_SERVER = """for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    if method == 'initialize':
        result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'fixture', 'version': '1'}}
    elif method == 'tools/list':
        cursor = request.get('params', {}).get('cursor', '')
        result = pages[cursor] if pages else {'tools': []}
    elif method == 'tools/call':
        result = call
    else:
        result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
"""


@contextmanager
def native_client(tmp_path, call_result=None, pages=None):
    script = tmp_path / "server.py"
    script.write_text(f"import json,sys\ncall={call_result!r}\npages={pages!r}\n" + _SERVER)
    client = McpClient({"name": "fixture", "type": "stdio", "command": sys.executable, "args": [str(script)], "timeout": 3})
    assert client.initialize()
    try:
        yield client
    finally:
        client.shutdown()


def test_discovers_every_page(tmp_path):
    pages = {
        "": {"tools": [{"name": "first"}], "nextCursor": "page-2"},
        "page-2": {"tools": [{"name": "second"}], "nextCursor": "page-3"},
        "page-3": {"tools": [{"name": "third"}]},
    }
    with native_client(tmp_path, pages=pages) as client:
        assert [tool["name"] for tool in client.list_tools()] == ["first", "second", "third"]


def test_cursor_cycle_is_rejected(tmp_path):
    pages = {"": {"tools": [{"name": "first"}], "nextCursor": "again"},
             "again": {"tools": [{"name": "second"}], "nextCursor": "again"}}
    with native_client(tmp_path, pages=pages) as client:
        assert client.list_tools() == []


@pytest.mark.parametrize("data", [{"value": 42, "label": "café"}, {}])
def test_structured_only_result_survives(tmp_path, data):
    with native_client(tmp_path, call_result={"content": [], "structuredContent": data}) as client:
        result = client.call_tool("fixture", {})
    assert json.loads(result) == data


def test_text_result_is_not_duplicated_by_structured_content(tmp_path):
    call = {"content": [{"type": "text", "text": "existing"}], "structuredContent": {"value": 42}}
    with native_client(tmp_path, call_result=call) as client:
        assert client.call_tool("fixture", {}) == "existing"


@pytest.mark.parametrize("content, detail", [
    ([{"type": "text", "text": "rate limit exceeded"}], "rate limit exceeded"),
    ([], "MCP tool execution failed"),
])
def test_is_error_reaches_tool_status(tmp_path, content, detail):
    with native_client(tmp_path, call_result={"content": content, "isError": True}) as client:
        result = McpTool(client, {"name": "fixture"}, "fixture").execute({})
    assert result.status == "error", result.result
    assert detail in result.result


def test_structured_error_detail_reaches_tool_status(tmp_path):
    call = {"content": [], "structuredContent": {"reason": "quota"}, "isError": True}
    with native_client(tmp_path, call_result=call) as client:
        result = McpTool(client, {"name": "fixture"}, "fixture").execute({})
    assert result.status == "error"
    assert "quota" in result.result


def test_success_stays_success(tmp_path):
    call = {"content": [{"type": "text", "text": "done"}], "isError": False}
    with native_client(tmp_path, call_result=call) as client:
        result = McpTool(client, {"name": "fixture"}, "fixture").execute({})
    assert result.status == "success"
    assert result.result == "done"
