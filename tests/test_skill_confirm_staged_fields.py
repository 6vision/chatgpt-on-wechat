"""Console skill confirm keeps the registry's presentation fields.

A preview fetched from a configured Skill Hub registry stages the skill
together with the fields the registry returned (category,
display_description, icon, version) in the staging directory's
skills_config.json. commit_staged forwards only source and display_name,
and the staging directory is discarded right after the confirm, so
without the fix the confirm silently drops the rest -- while the plain
install action records the caller's meta through record_install. Same
file, same feature, two paths that disagree.
"""
import json
import time
from unittest.mock import patch

import pytest

import cli.commands.skill as skill_cmd
from agent.skills.manager import SkillManager, apply_install_fields
from agent.skills.service import SkillService
from channel.web.api import skills as skills_api
from channel.web.web_channel import SkillsHandler


def _skill_md(name, desc="does things"):
    return f"---\nname: {name}\ndescription: {desc}\n---\n# {name}\n".encode("utf-8")


@pytest.fixture
def live_dir(tmp_path, monkeypatch):
    live = tmp_path / "live" / "skills"
    live.mkdir(parents=True)
    monkeypatch.setattr(skill_cmd, "get_skills_dir", lambda agent_id=None: str(live))
    return live


def _service(live_dir):
    builtin = live_dir / "none"
    builtin.mkdir(exist_ok=True)
    return SkillService(SkillManager(builtin_dir=str(builtin), custom_dir=str(live_dir)))


def _stage_from_local(tmp_path):
    """Stage one skill the way a registry install leaves the staging dir."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "SKILL.md").write_bytes(_skill_md("weekly-report", "Draft weekly reports"))
    stage = tmp_path / "stage"

    def fake_route(name, result, agent_id=None):
        skill_cmd._install_local(str(src), result, agent_id=agent_id)

    original = skill_cmd._route_install
    skill_cmd._route_install = fake_route
    try:
        result = skill_cmd.stage_skill("weekly-report", str(stage))
    finally:
        skill_cmd._route_install = original
    assert result.installed == ["weekly-report"]

    # What the configured registry said about the skill, recorded into the
    # staged config during staging (cli/commands/skill.py _record_hub_fields).
    config_path = stage / "skills_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    apply_install_fields(config["weekly-report"], {
        "category": "market",
        "display_name": "Weekly Report",
        "display_description": "整理本周工作",
        "icon": "https://cdn.example.test/icon.png",
        "version": "1.2.0",
    })
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return stage


def _confirm(stage, svc):
    token = "confirm-fields-token"
    skills_api._staging._items[token] = {"dir": str(stage), "agent_id": "", "created": time.time()}
    try:
        with patch.object(skills_api, "_require_auth"), \
                patch.object(skills_api.web, "header"), \
                patch.object(skills_api.web, "data",
                             return_value=json.dumps({"action": "confirm", "token": token}).encode()), \
                patch.object(skills_api, "_skill_service", return_value=svc):
            return json.loads(SkillsHandler().POST())
    finally:
        skills_api._staging.discard(token)


def test_confirm_keeps_the_registrys_presentation_fields(tmp_path, live_dir):
    stage = _stage_from_local(tmp_path)
    svc = _service(live_dir)

    resp = _confirm(stage, svc)

    assert resp["status"] == "success", resp
    entry = json.loads((live_dir / "skills_config.json").read_text(encoding="utf-8"))["weekly-report"]
    assert entry["category"] == "market"
    assert entry["display_name"] == "Weekly Report"
    assert entry["display_description"] == "整理本周工作"
    assert entry["icon"] == "https://cdn.example.test/icon.png"
    assert entry["version"] == "1.2.0"


def test_confirm_without_registry_fields_keeps_existing_ones(tmp_path, live_dir):
    stage = _stage_from_local(tmp_path)
    config_path = stage / "skills_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    entry = config["weekly-report"]
    for key in ("display_description", "icon", "version"):
        entry.pop(key, None)
    entry["category"] = "skill"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    (live_dir / "weekly-report").mkdir()
    (live_dir / "weekly-report" / "SKILL.md").write_bytes(_skill_md("weekly-report"))
    (live_dir / "skills_config.json").write_text(json.dumps({"weekly-report": {
        "name": "weekly-report", "enabled": True, "source": "linkai", "category": "market",
        "icon": "https://cdn.example.test/icon.png", "version": "1.0.0",
    }}), encoding="utf-8")
    svc = _service(live_dir)

    resp = _confirm(stage, svc)

    assert resp["status"] == "success", resp
    entry = json.loads((live_dir / "skills_config.json").read_text(encoding="utf-8"))["weekly-report"]
    assert entry["category"] == "market"
    assert entry["icon"] == "https://cdn.example.test/icon.png"
    assert entry["version"] == "1.0.0"
