import sys
from contextlib import contextmanager
from agent.tools.mcp.mcp_client import McpClient

@contextmanager
def native_client(tmp_path, call_result=None, pages=None):
    script = tmp_path / "server.py"
    script.write_text("import json,sys\n" + "call=" + repr(call_result) + "\npages=" + repr(pages) + "\n" + """for line in sys.stdin:
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
""")
    client = McpClient({"name": "fixture", "type": "stdio", "command": sys.executable, "args": [str(script)], "timeout": 3})
    assert client.initialize()
    try:
        yield client
    finally:
        client.shutdown()

import pytest
from agent.tools.mcp.mcp_tool import McpTool

@pytest.mark.parametrize("content, detail", [([{"type": "text", "text": "rate limit exceeded"}], "rate limit exceeded"), ([], "MCP tool execution failed")])
def test_native_mcp_iserror_reaches_tool_status(tmp_path, content, detail):
    with native_client(tmp_path, call_result={"content": content, "isError": True}) as client:
        result = McpTool(client, {"name": "fixture"}, "fixture").execute({})
    assert result.status == "error", result.result
    assert detail in result.result

def test_native_mcp_success_stays_success(tmp_path):
    with native_client(tmp_path, call_result={"content": [{"type": "text", "text": "done"}], "isError": False}) as client:
        result = McpTool(client, {"name": "fixture"}, "fixture").execute({})
    assert result.status == "success"
    assert result.result == "done"
