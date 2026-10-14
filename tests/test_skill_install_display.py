"""Presentation fields an install leaves in skills_config.json.

An install payload may say how a skill presents itself - ``display_name``,
``display_description``, ``icon``, ``version`` - next to its ``category``. They
are not in SKILL.md, so every rescan has to keep them, and an entry without them
has to read as before.
"""
import io
import json
import zipfile

from agent.skills.manager import SkillManager
from agent.skills.service import SkillService


def _skill_md(name, description="Demo skill"):
    return f"---\nname: {name}\ndescription: {description}\n---\n\nBody\n"


def _zip(dir_name, skill_md):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{dir_name}/SKILL.md", skill_md)
    return buf.getvalue()


def _service(tmp_path):
    builtin = tmp_path / "builtin"
    custom = tmp_path / "custom"
    builtin.mkdir()
    custom.mkdir()
    return SkillService(SkillManager(builtin_dir=str(builtin), custom_dir=str(custom))), custom


def _install(svc, monkeypatch, payload, archive):
    def fake_download(url, dest):
        with open(dest, "wb") as f:
            f.write(archive)

    monkeypatch.setattr(svc, "_download_file", fake_download)
    svc.add(dict({"type": "package", "files": [{"url": "https://cdn.example.com/p.zip"}]}, **payload))


def _config(custom):
    return json.loads((custom / "skills_config.json").read_text(encoding="utf-8"))


def test_install_records_presentation_fields(tmp_path, monkeypatch):
    svc, custom = _service(tmp_path)
    _install(svc, monkeypatch, {
        "name": "weekly-report", "category": "market", "display_name": "Weekly  Report",
        "icon": "https://cdn.example.com/icon.png", "version": "1.2.0",
    }, _zip("weekly-report", _skill_md("weekly-report")))

    entry = _config(custom)["weekly-report"]
    assert entry["category"] == "market"
    assert entry["display_name"] == "Weekly Report"
    assert entry["icon"] == "https://cdn.example.com/icon.png"
    assert entry["version"] == "1.2.0"
    # The description shown is the one in SKILL.md
    assert entry["description"] == "Demo skill"

    queried = {s["name"]: s for s in svc.query()}["weekly-report"]
    assert queried["icon"] == "https://cdn.example.com/icon.png"
    assert queried["version"] == "1.2.0"


def test_rescan_keeps_presentation_fields(tmp_path, monkeypatch):
    svc, custom = _service(tmp_path)
    _install(svc, monkeypatch, {
        "name": "weekly-report", "icon": "https://cdn.example.com/icon.png", "version": "1.0.0",
    }, _zip("weekly-report", _skill_md("weekly-report")))

    (custom / "weekly-report" / "SKILL.md").write_text(
        _skill_md("weekly-report", "Edited"), encoding="utf-8")
    fresh = SkillManager(builtin_dir=str(tmp_path / "builtin"), custom_dir=str(custom))
    fresh.refresh_skills()

    entry = _config(custom)["weekly-report"]
    assert entry["description"] == "Edited"
    assert entry["icon"] == "https://cdn.example.com/icon.png"
    assert entry["version"] == "1.0.0"


def test_reinstall_without_package_fields_drops_stale_ones(tmp_path, monkeypatch):
    svc, custom = _service(tmp_path)
    archive = _zip("weekly-report", _skill_md("weekly-report"))
    _install(svc, monkeypatch, {
        "name": "weekly-report", "display_name": "Weekly",
        "icon": "https://cdn.example.com/icon.png", "version": "1.0.0",
    }, archive)
    _install(svc, monkeypatch, {"name": "weekly-report"}, archive)

    entry = _config(custom)["weekly-report"]
    assert "icon" not in entry
    assert "version" not in entry
    # A title is not tied to one package, so it stays
    assert entry["display_name"] == "Weekly"


def test_display_description_is_shown_but_the_agent_reads_skill_md(tmp_path, monkeypatch):
    svc, custom = _service(tmp_path)
    archive = _zip("weekly-report", _skill_md("weekly-report", "Draft weekly reports"))
    _install(svc, monkeypatch, {"name": "weekly-report", "display_description": "整理  本周工作"}, archive)

    entry = _config(custom)["weekly-report"]
    assert entry["display_description"] == "整理 本周工作"
    assert entry["description"] == "Draft weekly reports"
    assert svc.manager.get_skill("weekly-report").skill.description == "Draft weekly reports"

    # Like the title, it outlives a rescan and a reinstall that does not carry it
    _install(svc, monkeypatch, {"name": "weekly-report"}, archive)
    SkillManager(builtin_dir=str(tmp_path / "builtin"), custom_dir=str(custom)).refresh_skills()
    assert _config(custom)["weekly-report"]["display_description"] == "整理 本周工作"


def test_unusable_fields_are_ignored(tmp_path, monkeypatch):
    svc, custom = _service(tmp_path)
    _install(svc, monkeypatch, {
        "name": "weekly-report", "icon": "javascript:alert(1)", "version": 3, "display_name": "",
    }, _zip("weekly-report", _skill_md("weekly-report")))

    entry = _config(custom)["weekly-report"]
    assert "icon" not in entry
    assert "version" not in entry
    assert "display_name" not in entry


def test_fields_land_on_the_skill_md_name_when_it_differs(tmp_path, monkeypatch):
    svc, custom = _service(tmp_path)
    _install(svc, monkeypatch, {
        "name": "weekly-report", "category": "market", "version": "1.0.0",
    }, _zip("weekly-report", _skill_md("weekly-summary")))

    config = _config(custom)
    assert "weekly-report" not in config
    assert config["weekly-summary"]["category"] == "market"
    assert config["weekly-summary"]["version"] == "1.0.0"


def _console_install(svc, custom, body, installed):
    from unittest.mock import patch

    from channel.web.web_channel import SkillsHandler
    from channel.web.api import skills as skills_api
    from cli.commands.skill import InstallResult

    def fake_install(spec, agent_id=None):
        for name in installed:
            (custom / name).mkdir()
            (custom / name / "SKILL.md").write_text(_skill_md(name), encoding="utf-8")
        result = InstallResult()
        result.installed = list(installed)
        return result

    with patch.object(skills_api, "_require_auth"), \
            patch.object(skills_api.web, "header"), \
            patch.object(skills_api.web, "data", return_value=json.dumps(body).encode()), \
            patch.object(skills_api, "_skill_service", return_value=svc), \
            patch.object(skills_api, "_install_skill_for_agent", fake_install):
        return json.loads(SkillsHandler().POST())


def test_console_install_records_the_callers_meta(tmp_path):
    svc, custom = _service(tmp_path)
    resp = _console_install(svc, custom, {
        "action": "install", "spec": "https://cdn.example.com/weekly-report.zip",
        "meta": {"category": "private", "display_name": "Weekly Report", "version": "2.0.0"},
    }, ["weekly-report"])

    assert resp["status"] == "success"
    entry = _config(custom)["weekly-report"]
    assert entry["category"] == "private"
    assert entry["display_name"] == "Weekly Report"
    assert entry["version"] == "2.0.0"


def test_console_install_of_several_skills_ignores_meta(tmp_path):
    svc, custom = _service(tmp_path)
    _console_install(svc, custom, {
        "action": "install", "spec": "owner/repo", "meta": {"category": "private", "version": "2.0.0"},
    }, ["alpha", "beta"])

    config = _config(custom)
    assert config["alpha"]["category"] == "skill" and "version" not in config["alpha"]
    assert config["beta"]["category"] == "skill" and "version" not in config["beta"]


def test_new_skill_is_stamped_with_install_time_and_keeps_it(tmp_path):
    custom = tmp_path / "custom"
    (custom / "alpha").mkdir(parents=True)
    (custom / "alpha" / "SKILL.md").write_text(_skill_md("alpha"), encoding="utf-8")
    manager = SkillManager(builtin_dir=str(tmp_path / "none"), custom_dir=str(custom))
    stamped = _config(custom)["alpha"]["installed_at"]
    assert isinstance(stamped, int) and stamped > 0

    manager.refresh_skills()
    assert _config(custom)["alpha"]["installed_at"] == stamped


def test_existing_config_without_new_fields_reads_unchanged(tmp_path):
    custom = tmp_path / "custom"
    (custom / "alpha").mkdir(parents=True)
    (custom / "alpha" / "SKILL.md").write_text(_skill_md("alpha"), encoding="utf-8")
    legacy = {"alpha": {"name": "alpha", "description": "Demo skill", "source": "custom",
                        "enabled": False, "category": "skill", "display_name": "Alpha"}}
    (custom / "skills_config.json").write_text(json.dumps(legacy), encoding="utf-8")
    before = (custom / "skills_config.json").read_text(encoding="utf-8")

    SkillManager(builtin_dir=str(tmp_path / "none"), custom_dir=str(custom)).refresh_skills()

    assert _config(custom) == legacy
    # Nothing changed, so the file is not rewritten
    assert (custom / "skills_config.json").read_text(encoding="utf-8") == before
