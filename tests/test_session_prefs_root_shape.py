import json
import pytest
from agent.workspace import session_prefs

@pytest.mark.parametrize("payload", [["unexpected"], "unexpected", 42, True])
def test_valid_nonobject_json_does_not_break_preferences(tmp_path, monkeypatch, payload):
    path = tmp_path / "session_prefs.json"
    path.write_text(json.dumps(payload))
    original = path.read_text()
    monkeypatch.setattr(session_prefs, "_store_file", lambda: str(path))
    assert session_prefs.get_prefs("s1") == {}
    assert session_prefs.members_index() == {}
    session_prefs.forget_session("s1")
    assert path.read_text() == original
    assert session_prefs.set_prefs("s1", model="chosen") == {"model": "chosen"}
    assert session_prefs.get_prefs("s1") == {"model": "chosen"}

def test_well_formed_preferences_keep_unrelated_sessions(tmp_path, monkeypatch):
    path = tmp_path / "session_prefs.json"
    path.write_text(json.dumps({"sessions": {"default::other": {"model": "retained"}}}))
    monkeypatch.setattr(session_prefs, "_store_file", lambda: str(path))
    session_prefs.set_prefs("s1", permission="read-only")
    assert session_prefs.get_prefs("other") == {"model": "retained"}
