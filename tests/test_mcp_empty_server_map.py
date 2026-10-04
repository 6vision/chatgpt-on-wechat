"""An mcp.json with no servers must read as no servers, everywhere.

``save_servers`` writes ``{"mcpServers": {}}`` when the last server is removed
in the console (``skills.py``'s PUT handler calls it with whatever list the
browser posted, and an empty list is valid). Two readers then disagree about
what "empty" means:

* ``service.load_servers`` -- what the console shows -- tests the key with
  ``is None``, so ``{}`` stays an empty map and yields no servers;
* ``ToolManager._load_mcp_configs`` -- what actually boots -- chained ``or``,
  and ``{}`` is falsy, so it fell through to the whole document and read the
  wrapper key ``mcpServers`` as a server name.

Measured, through the real loaders:

    reader A (console) : []
    reader B (runtime) : [{'name': 'mcpServers', 'type': 'stdio'}]   <- no 'command'

That ghost also defeats the ``if not mcp_servers_config`` short circuit in
``_load_mcp_tools``, so every agent init forks a loader thread for it, and
``_mcp_status['mcpServers'] = 'failed'`` is never popped -- the only pop is in
``_teardown_mcp_server``, keyed by the real server name. Since the file on disk
keeps producing the ghost, it comes back on every boot until the file is edited
by hand.
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent.tools.mcp import service  # noqa: E402
from agent.tools.tool_manager import ToolManager  # noqa: E402


def _reader_b(workspace):
    """The runtime reader, with only what it needs wired up."""
    manager = ToolManager.__new__(ToolManager)
    manager.workspace_root = workspace
    return manager._load_mcp_configs()


class McpEmptyServerMapTest(unittest.TestCase):
    """Both readers have to agree, and neither may invent a server."""

    def setUp(self):
        self.workspace = tempfile.mkdtemp(prefix="mcp-empty-")

    def _write(self, payload):
        path = service.mcp_config_path(self.workspace)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_an_empty_server_map_reads_as_no_servers(self):
        self._write({"mcpServers": {}})

        self.assertEqual(service.load_servers(self.workspace), [])
        self.assertEqual(
            _reader_b(self.workspace), [],
            "the runtime read a server out of an empty server map",
        )

    def test_what_the_editor_writes_for_no_servers_reads_as_no_servers(self):
        # The real generator, rather than a hand-written fixture.
        service.save_servers(self.workspace, [])

        self.assertEqual(_reader_b(self.workspace), [])

    def test_an_empty_snake_case_map_reads_as_no_servers(self):
        self._write({"mcp_servers": {}})

        self.assertEqual(_reader_b(self.workspace), [])

    def test_the_readers_agree_with_a_real_server(self):
        service.save_servers(self.workspace, [{
            "name": "demo",
            "command": "npx",
            "args": ["-y", "demo"],
        }])

        console = {s["name"] for s in service.load_servers(self.workspace)}
        runtime = {s["name"] for s in _reader_b(self.workspace)}

        self.assertEqual(console, {"demo"})
        self.assertEqual(console, runtime)

    def test_a_flat_file_with_servers_at_the_top_level_still_works(self):
        # A hand-edited mcp.json may hold servers at the top level; the wrapper
        # key is absent there, so the document itself is the server map.
        self._write({"demo": {"command": "npx", "args": []}})

        self.assertEqual({s["name"] for s in _reader_b(self.workspace)}, {"demo"})

    def test_an_empty_document_is_still_no_servers(self):
        self._write({})

        self.assertEqual(_reader_b(self.workspace), [])


if __name__ == "__main__":
    unittest.main()