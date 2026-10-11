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

def test_native_mcp_discovers_every_page(tmp_path):
    pages = {"": {"tools": [{"name": "first"}], "nextCursor": "page-2"}, "page-2": {"tools": [{"name": "second"}], "nextCursor": "page-3"}, "page-3": {"tools": [{"name": "third"}]}}
    with native_client(tmp_path, pages=pages) as client:
        assert [tool["name"] for tool in client.list_tools()] == ["first", "second", "third"]

def test_native_mcp_cursor_cycle_is_rejected(tmp_path):
    pages = {"": {"tools": [{"name": "first"}], "nextCursor": "again"}, "again": {"tools": [{"name": "second"}], "nextCursor": "again"}}
    with native_client(tmp_path, pages=pages) as client:
        assert client.list_tools() == []
