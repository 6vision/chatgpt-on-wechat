"""CLI installs must read the same valid YAML metadata as the skill loader."""
import json
import os
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from agent.skills.frontmatter import parse_frontmatter
from cli.commands.skill import skill
from cli.utils import get_skills_dir


@pytest.mark.parametrize("header, description", [
    ("name: demo\ndescription: ordinary skill", "ordinary skill"),
    ('name: "demo" # a normal YAML comment\ndescription: ordinary skill', "ordinary skill"),
    ("name: demo\ndescription: |\n  Run local commands.\n  Keep their results.",
     "Run local commands.\nKeep their results."),
    ("name: demo\ndescription: >-\n  Run local commands\n  and keep their results.",
     "Run local commands and keep their results."),
    ("name: demo\ndescription: |\n  Explain these document fields:\n  name: ledger\n  description: user-visible label",
     "Explain these document fields:\nname: ledger\ndescription: user-visible label"),
    ("name: demo\ndescription: 'The user''s helper'", "The user's helper"),
])
def test_public_url_install_preserves_loader_metadata_and_existing_skill(tmp_path, header, description):
    payload = ("---\n" + header + "\n---\n\n# Demo\n").encode()
    assert parse_frontmatter(payload.decode()) == {"name": "demo", "description": description}
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    home, data, workspace = (tmp_path / name for name in ("home", "data", "workspace"))
    home.mkdir()
    data.mkdir()
    skills = workspace / "skills"
    skills.mkdir(parents=True)
    victim = skills / "ledger" / "SKILL.md"
    victim.parent.mkdir()
    original = b"---\nname: ledger\ndescription: existing user's skill\n---\n# Keep me\n"
    victim.write_bytes(original)
    (data / "config.json").write_text(json.dumps({"agent_workspace": str(workspace)}), encoding="utf-8")
    try:
        with patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home),
                                     "COW_DATA_DIR": str(data)}, clear=True):
            target = Path(get_skills_dir()).resolve()
            assert os.path.commonpath([str(target), str(tmp_path.resolve())]) == str(tmp_path.resolve())
            installed = CliRunner().invoke(skill, ["install", f"http://127.0.0.1:{server.server_port}/SKILL.md"])
            listed = CliRunner().invoke(skill, ["list"])
        assert installed.exit_code == 0, installed.output
        assert listed.exit_code == 0, listed.output
        assert hits == ["/SKILL.md"]
        assert (target / "demo" / "SKILL.md").read_bytes() == payload
        registry = json.loads((target / "skills_config.json").read_text(encoding="utf-8"))
        assert registry["demo"]["description"] == description
        assert registry["ledger"]["description"] == "existing user's skill"
        assert victim.read_bytes() == original
        display = " ".join(description.split())
        if len(display) > 40:
            display = display[:37] + "..."
        assert any(line.startswith("  demo ") and line.endswith(display)
                   for line in listed.output.splitlines())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
