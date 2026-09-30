"""A BOM in skills_config.json must not silently re-enable disabled skills.

``skills_config.json`` lives in the workspace ``skills/`` directory, so it is a
file the user opens and re-saves -- Windows Notepad and PowerShell write a
UTF-8 BOM by default. ``cli.utils.load_skills_config`` read it as plain utf-8,
which turns the leading BOM into the ``\\ufeff`` character so ``json.load``
raises; the helper swallows that and answers ``{}``.

``cow skill list`` then rebuilds the table from the directories on disk and
writes it back, and that rebuild assumes ``enabled: True``. A skill the user had
turned off comes back on, the BOM disappears with the rewrite, and nothing is
printed to say so -- the file now records a choice the user never made.

The same helper already reads config.json as ``utf-8-sig`` a few lines above, so
the convention is established in the file itself.
"""
import json
import os
import sys

from click.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli.utils import load_skills_config  # noqa: E402
from cli.commands import skill as cli_skill  # noqa: E402

CONFIG = {
    "alpha": {"name": "alpha", "source": "custom", "enabled": True, "category": "skill"},
    "beta": {"name": "beta", "source": "cowhub", "enabled": False, "category": "skill"},
}


def _skills_dir(tmp_path, bom=True):
    """A skills dir whose config was re-saved by a Windows editor."""
    skills_dir = tmp_path / "skills"
    for name in ("alpha", "beta"):
        (skills_dir / name).mkdir(parents=True)
        (skills_dir / name / "SKILL.md").write_text(
            "---\nname: %s\ndescription: Demo\n---\n" % name, encoding="utf-8"
        )
    encoding = "utf-8-sig" if bom else "utf-8"
    (skills_dir / "skills_config.json").write_text(
        json.dumps(CONFIG, ensure_ascii=False), encoding=encoding
    )
    return skills_dir


def _pin(skills_dir, tmp_path, monkeypatch):
    """Point the CLI and the helper at the temporary skills dir."""
    monkeypatch.setattr(cli_skill, "get_skills_dir", lambda *a, **k: str(skills_dir))
    monkeypatch.setattr(
        cli_skill, "get_builtin_skills_dir", lambda *a, **k: str(tmp_path / "none")
    )
    monkeypatch.setattr("cli.utils.get_skills_dir", lambda *a, **k: str(skills_dir))


def _read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def test_load_skills_config_reads_a_bom_encoded_file(tmp_path, monkeypatch):
    skills_dir = _skills_dir(tmp_path)
    _pin(skills_dir, tmp_path, monkeypatch)

    assert load_skills_config() == CONFIG, (
        "a skills_config.json saved with a BOM must still load"
    )


def test_listing_does_not_re_enable_a_disabled_skill(tmp_path, monkeypatch):
    """The user-visible half: a skill turned off must stay off."""
    skills_dir = _skills_dir(tmp_path)
    _pin(skills_dir, tmp_path, monkeypatch)
    config_path = skills_dir / "skills_config.json"

    result = CliRunner().invoke(cli_skill.skill_list, [])
    assert result.exit_code == 0, result.output

    assert _read(config_path)["beta"]["enabled"] is False, (
        "listing skills must not turn a disabled skill back on"
    )


def test_a_bom_less_file_still_loads(tmp_path, monkeypatch):
    """Control: the fix must not change behaviour for files without a BOM."""
    skills_dir = _skills_dir(tmp_path, bom=False)
    _pin(skills_dir, tmp_path, monkeypatch)

    assert load_skills_config() == CONFIG
