"""Public env updates must preserve the dotenv values loaded at startup."""

import os

import pytest
from dotenv import load_dotenv

from agent.tools.env_config.env_config import EnvConfig


@pytest.mark.parametrize("entry, expected", [
    ('"fixture-token"', "fixture-token"),
    ("'fixture-token'", "fixture-token"),
    ("fixture-token # explanation", "fixture-token"),
    ('"fixture\\\\token"', "fixture\\token"),
    ('"${COW_RELOAD_BASE}-token"', "fixture-token"),
    ("plain-token", "plain-token"),
], ids=["double-quoted", "single-quoted", "inline-comment", "escaped-backslash", "expansion", "plain-control"])
def test_public_set_keeps_startup_dotenv_value(tmp_path, monkeypatch, entry, expected):
    monkeypatch.setenv("COW_RELOAD_BASE", "fixture")
    monkeypatch.setenv("COW_RELOAD_EXISTING", "before")
    monkeypatch.setenv("COW_RELOAD_NEW", "before")
    path = tmp_path / ".env"
    path.write_text("COW_RELOAD_EXISTING=" + entry + "\n", encoding="utf-8")
    load_dotenv(path, override=True)
    assert os.environ["COW_RELOAD_EXISTING"] == expected

    class Bridge:
        refreshed = False

        def refresh_all_skills(self):
            self.refreshed = True
            return 1

    bridge = Bridge()
    tool = EnvConfig({"agent_bridge": bridge})
    tool.env_dir = str(tmp_path)
    tool.env_path = str(path)
    result = tool.execute({"action": "set", "key": "COW_RELOAD_NEW", "value": "new-token"})

    assert result.status == "success"
    assert bridge.refreshed
    assert os.environ["COW_RELOAD_EXISTING"] == expected
    assert os.environ["COW_RELOAD_NEW"] == "new-token"
