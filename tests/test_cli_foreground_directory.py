"""Native foreground launch preserves project-relative workspace resolution."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import click
import pytest


@pytest.mark.skipif(os.name != "posix", reason="native POSIX foreground exec path")
@pytest.mark.parametrize("case", [
    "relative_root", "relative_outside", "automatic_terminal_outside", "absolute_outside",
])
def test_foreground_launch_preserves_existing_workspace(tmp_path, case):
    source = Path(__file__).resolve().parents[1]
    project = tmp_path / "project"
    project.mkdir()
    shutil.copytree(source / "cli", project / "cli", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(source / "config.py", project / "config.py")
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = project / "workspace"
    workspace.mkdir()
    (workspace / "MEMORY.md").write_text("owned existing memory", encoding="utf-8")
    (project / "config.json").write_text(json.dumps({
        "agent_workspace": str(workspace) if case == "absolute_outside" else "./workspace",
        "channel_type": ["terminal"], "cow_lang": "en", "model": "owned-unused-model",
    }), encoding="utf-8")
    # Observe canonical startup resolution without starting a gateway or model.
    (project / "app.py").write_text('''import json
from pathlib import Path
from config import load_config, conf
from agent import team
from agent.registry import AgentRegistry
load_config()
profile = AgentRegistry.from_config(team.resolve(conf())).get(require_enabled=False)
path = Path(profile.workspace) / "MEMORY.md"
print("NATIVE_RESULT=" + json.dumps({"workspace": profile.workspace,
    "memory": path.read_text(encoding="utf-8") if path.is_file() else None}))
''', encoding="utf-8")
    env = {
        "PATH": os.defpath, "HOME": str(home), "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"), "XDG_CACHE_HOME": str(home / ".cache"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join(map(str, [
            project, source, Path(click.__file__).parent.parent,
        ])),
    }
    arguments = [] if case == "automatic_terminal_outside" else ["--foreground"]
    result = subprocess.run([
        sys.executable, "-c", "from cli.commands.process import start; start.main()", *arguments,
    ], cwd=project if case == "relative_root" else outside, env=env,
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line.removeprefix("NATIVE_RESULT=") for line in result.stdout.splitlines()
             if line.startswith("NATIVE_RESULT=")]
    assert lines, result.stdout + result.stderr
    observed = json.loads(lines[-1])
    assert observed["workspace"] == str(workspace.resolve())
    assert observed["memory"] == "owned existing memory"
