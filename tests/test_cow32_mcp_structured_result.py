import json
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

@pytest.mark.parametrize("data", [{"value": 42, "label": "café"}, {}])
def test_native_mcp_structured_result_survives(tmp_path, data):
    with native_client(tmp_path, call_result={"content": [], "structuredContent": data}) as client:
        result = client.call_tool("fixture", {})
    assert result, "structured data was discarded"
    assert json.loads(result) == data

def test_native_mcp_text_result_is_not_duplicated(tmp_path):
    with native_client(tmp_path, call_result={"content": [{"type": "text", "text": "existing"}], "structuredContent": {"value": 42}}) as client:
        assert client.call_tool("fixture", {}) == "existing"
