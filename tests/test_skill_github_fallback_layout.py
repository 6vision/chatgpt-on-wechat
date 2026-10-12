"""Contents API fallback installs must preserve the skill's runnable layout."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import unquote, urlparse

import pytest
import requests
from click.testing import CliRunner

from cli.commands.skill import skill
from cli.utils import get_skills_dir


@pytest.mark.parametrize("scripts", [
    {"run.py": b"print('flat')\n"},
    {"scripts/run.py": b"print('nested')\n"},
    {"scripts/tools/run.py": b"print('deep')\n"},
    {"scripts/run.py": b"print('script')\n", "references/run.py": b"print('reference')\n"},
])
def test_contents_fallback_keeps_paths_and_equal_basenames(tmp_path, scripts):
    files = {"SKILL.md": b"---\nname: demo\ndescription: fixture skill\n---\n", **scripts}
    requested = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            requested.append(path)
            if path.startswith("/archive/"):
                self.send_error(503, "archive unavailable")
                return
            if path.startswith("/files/"):
                payload = files[path[len("/files/"):]]
            else:
                prefix = path.split("/contents/", 1)[1].removeprefix("skills/demo").strip("/")
                descendants = [name[len(prefix) + 1:] if prefix else name
                               for name in files if not prefix or name.startswith(prefix + "/")]
                items = []
                for part in sorted({name.split("/")[0] for name in descendants}):
                    relative = "/".join(p for p in (prefix, part) if p)
                    item = {"path": "skills/demo/" + relative,
                            "type": "file" if relative in files else "dir"}
                    if item["type"] == "file":
                        item["download_url"] = base + "/files/" + relative
                    items.append(item)
                payload = json.dumps(items).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = "http://127.0.0.1:" + str(server.server_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    get = requests.get

    def routed_get(url, **kwargs):
        # Only routing is substituted; responses and body reads use real HTTP.
        if url.startswith("https://github.com/owner/repo/archive/"):
            url = base + "/archive/unavailable.zip"
        elif url.startswith("https://api.github.com/repos/owner/repo/contents/"):
            url = base + urlparse(url).path
        assert url.startswith(base + "/"), "test attempted an external request"
        return get(url, **kwargs)

    home, data, workspace = (tmp_path / name for name in ("home", "data", "workspace"))
    home.mkdir()
    data.mkdir()
    (workspace / "skills").mkdir(parents=True)
    (data / "config.json").write_text(json.dumps({"agent_workspace": str(workspace)}), encoding="utf-8")
    try:
        with patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home),
                                     "COW_DATA_DIR": str(data)}, clear=True), \
                patch.object(requests, "get", routed_get):
            target = Path(get_skills_dir()).resolve() / "demo"
            assert os.path.commonpath([str(target), str(tmp_path.resolve())]) == str(tmp_path.resolve())
            result = CliRunner().invoke(skill, ["install", "https://github.com/owner/repo/tree/main/skills/demo"])
        assert result.exit_code == 0, result.output
        assert "falling back to Contents API" in result.output
        assert any("/contents/" in path for path in requested)
        actual = {p.relative_to(target).as_posix(): p.read_bytes()
                  for p in target.rglob("*") if p.is_file()}
        assert actual == files
        for relative in scripts:
            execution = subprocess.run([sys.executable, str(target / relative)], capture_output=True, timeout=10)
            assert execution.returncode == 0, execution.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
