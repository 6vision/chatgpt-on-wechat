import sys
from agent.tools.bash.bash import Bash

def test_bare_dotenv_key_does_not_break_native_shell(tmp_path, monkeypatch):
    home = tmp_path / "home"
    folder = home / ".cow"
    folder.mkdir(parents=True)
    (folder / ".env").write_text("COW_BARE_KEY\nCOW_EMPTY_KEY=\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("COW_BARE_KEY", "inherited")
    monkeypatch.setenv("COW_EMPTY_KEY", "old")
    command = f"{sys.executable} -c \"import os; print(os.environ['COW_BARE_KEY'] + ':' + os.environ['COW_EMPTY_KEY'])\""
    result = Bash({"cwd": str(tmp_path)}).execute({"command": command})
    assert result.status == "success", result.result
    assert "inherited:" in result.result["output"]
