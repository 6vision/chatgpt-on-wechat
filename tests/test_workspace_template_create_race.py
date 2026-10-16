from unittest.mock import patch

from agent.prompt.workspace import _create_template_if_missing


def test_intervening_profile_creation_is_preserved(tmp_path):
    profile = tmp_path / "AGENT.md"
    saved_profile = "My personalized agent profile"

    def exists_before_concurrent_writer(path):
        assert str(path) == str(profile)
        profile.write_text(saved_profile, encoding="utf-8")
        return False

    with patch("agent.prompt.workspace.os.path.exists", side_effect=exists_before_concurrent_writer):
        _create_template_if_missing(str(profile), "Default template")
    assert profile.read_text(encoding="utf-8") == saved_profile


def test_missing_template_is_created(tmp_path):
    profile = tmp_path / "AGENT.md"
    _create_template_if_missing(str(profile), "Default template")
    assert profile.read_text(encoding="utf-8") == "Default template"


def test_existing_profile_is_preserved(tmp_path):
    profile = tmp_path / "AGENT.md"
    profile.write_text("Personal profile", encoding="utf-8")
    _create_template_if_missing(str(profile), "Default template")
    assert profile.read_text(encoding="utf-8") == "Personal profile"
