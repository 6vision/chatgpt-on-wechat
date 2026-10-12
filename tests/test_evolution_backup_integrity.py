"""A damaged undo snapshot must be rejected before any file is restored."""

import json

from agent.evolution.backup import create_backup, restore_backup


def test_missing_snapshot_refuses_without_partially_restoring(tmp_path):
    memory = tmp_path / "MEMORY.md"
    skill = tmp_path / "skills" / "custom" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    memory.write_text("original memory", encoding="utf-8")
    skill.write_text("original skill", encoding="utf-8")
    backup_id = create_backup(tmp_path, [memory, skill])
    snapshot = tmp_path / "memory" / ".evolution_backups" / backup_id
    (snapshot / "1.bak").unlink()
    memory.write_text("updated memory", encoding="utf-8")
    skill.write_text("updated skill", encoding="utf-8")

    assert restore_backup(tmp_path, backup_id) is False
    assert memory.read_text(encoding="utf-8") == "updated memory"
    assert skill.read_text(encoding="utf-8") == "updated skill"


def test_invalid_manifest_refuses_before_valid_earlier_entries_are_applied(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("original", encoding="utf-8")
    backup_id = create_backup(tmp_path, [memory])
    snapshot = tmp_path / "memory" / ".evolution_backups" / backup_id
    manifest = snapshot / "manifest.json"
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    entries.append({"rel": "skills/custom/SKILL.md"})
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    memory.write_text("updated", encoding="utf-8")

    assert restore_backup(tmp_path, backup_id) is False
    assert memory.read_text(encoding="utf-8") == "updated"

    manifest.write_text(json.dumps(entries[:1]), encoding="utf-8")
    assert restore_backup(tmp_path, backup_id) is True
    assert memory.read_text(encoding="utf-8") == "original"
