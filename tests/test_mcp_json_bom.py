"""A BOM in mcp.json must not make every configured MCP server unreadable.

``mcp.json`` is a file the docs tell users to write by hand ("A single mcp.json
is enough"), and Windows Notepad and PowerShell save it with a UTF-8 BOM.
``agent.tools.mcp.service._read_mcp_file`` opens it as plain utf-8, so the BOM
becomes a leading ``\\ufeff`` character and ``json.load`` raises; the helper
turns that into ``McpConfigError("mcp.json is not valid JSON: ...")``.

``load_servers`` and ``save_servers`` both go through it, so a BOM takes the
whole MCP surface down -- the console's server list, the runtime load, and any
save, which reads the file first to merge into it. The message names the JSON
rather than the BOM, so the file looks fine in an editor.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.mcp import service as mcp_service  # noqa: E402

SERVERS = {
    "mcpServers": {
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        }
    }
}


def _write_mcp_json(tmp_path, bom=True):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(SERVERS, ensure_ascii=False),
        encoding="utf-8-sig" if bom else "utf-8",
    )
    return path


def test_load_servers_reads_a_bom_encoded_mcp_json(tmp_path):
    _write_mcp_json(tmp_path)

    servers = mcp_service.load_servers(workspace=str(tmp_path))

    assert [s["name"] for s in servers] == ["filesystem"], (
        "a mcp.json saved with a BOM must still load its servers"
    )


def test_save_servers_does_not_fail_on_a_bom_encoded_mcp_json(tmp_path):
    """The user-visible half: saving reads the file first to merge into it."""
    _write_mcp_json(tmp_path)

    servers = mcp_service.load_servers(workspace=str(tmp_path))
    servers.append({"name": "memory", "command": "npx", "args": ["-y", "mcp-memory"]})

    saved = mcp_service.save_servers(str(tmp_path), servers)

    assert sorted(s["name"] for s in saved) == ["filesystem", "memory"]
    on_disk = json.loads((tmp_path / "mcp.json").read_text(encoding="utf-8-sig"))
    assert sorted(on_disk["mcpServers"]) == ["filesystem", "memory"]


def test_a_bom_less_mcp_json_still_loads(tmp_path):
    """Control: the fix must not change behaviour for files without a BOM."""
    _write_mcp_json(tmp_path, bom=False)

    servers = mcp_service.load_servers(workspace=str(tmp_path))

    assert [s["name"] for s in servers] == ["filesystem"]
