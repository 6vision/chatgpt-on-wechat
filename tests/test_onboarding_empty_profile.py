import pytest
from agent.prompt.workspace import load_context_files, _is_onboarding_done


@pytest.mark.parametrize("content", ["", " \n\t"])
def test_blank_profile_keeps_bootstrap_in_context(tmp_path, content):
    (tmp_path / "AGENT.md").write_text(content)
    bootstrap = tmp_path / "BOOTSTRAP.md"
    bootstrap.write_text("Ask the user to configure the profile.")
    assert not _is_onboarding_done(str(tmp_path))
    context = load_context_files(str(tmp_path), ["BOOTSTRAP.md"])
    assert len(context) == 1
    assert context[0].content == "Ask the user to configure the profile."
    assert bootstrap.exists()


def test_completed_profile_still_removes_bootstrap(tmp_path):
    (tmp_path / "AGENT.md").write_text("# Agent\nName: Helper")
    bootstrap = tmp_path / "BOOTSTRAP.md"
    bootstrap.write_text("Configure profile")
    assert _is_onboarding_done(str(tmp_path))
    assert load_context_files(str(tmp_path), ["BOOTSTRAP.md"]) == []
    assert not bootstrap.exists()
