"""Legacy reminders remain discoverable until the global store commits."""

import errno
import json
import os
from pathlib import Path

import pytest

from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from agent.tools.scheduler import integration
from agent.tools.scheduler.task_store import TaskStore


@pytest.fixture
def stores(tmp_path, monkeypatch):
    registry = AgentRegistry([
        AgentProfile("primary", "Primary", str(tmp_path / "primary")),
        AgentProfile("research", "Research", str(tmp_path / "research")),
    ], default_agent_id="primary")
    set_agent_registry(registry)
    monkeypatch.setattr(integration, "_legacy_stores_migrated", False)
    primary = tmp_path / "primary" / "scheduler" / "tasks.json"
    legacy = tmp_path / "research" / "scheduler" / "tasks.json"
    TaskStore(str(legacy)).add_task({"id": "reminder", "name": "Review the draft", "enabled": True})
    try:
        yield TaskStore(str(primary)), legacy
    finally:
        set_agent_registry(None)


def test_failed_global_write_retains_reminder_for_a_fresh_store(stores, monkeypatch):
    store, legacy = stores
    original = legacy.read_bytes()

    def disk_full(tasks):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(store, "save_tasks", disk_full)
    integration._migrate_legacy_task_stores(store)
    assert legacy.exists(), "The only durable reminder must remain discoverable"
    assert legacy.read_bytes() == original
    assert not Path(str(legacy) + ".migrated").exists()

    # A new process constructs another store and runs startup migration again.
    monkeypatch.setattr(integration, "_legacy_stores_migrated", False)
    fresh = TaskStore(store.store_path)
    integration._migrate_legacy_task_stores(fresh)
    reminder = TaskStore(store.store_path).get_task("reminder")
    assert reminder["name"] == "Review the draft"
    assert reminder["agent_id"] == "research"
    assert Path(str(legacy) + ".migrated").read_bytes() == original


def test_global_commit_precedes_retiring_every_legacy_source(stores, monkeypatch):
    store, legacy = stores
    replace = os.replace
    retired = []

    def observe(source, destination):
        if str(source) == str(legacy):
            # Read from disk through a new store, rather than inspecting the
            # migration's in-memory dictionary.
            assert TaskStore(store.store_path).get_task("reminder") is not None
            retired.append(str(source))
        return replace(source, destination)

    monkeypatch.setattr(integration.os, "replace", observe)
    integration._migrate_legacy_task_stores(store)
    assert retired == [str(legacy)]
    assert integration._legacy_stores_migrated


def test_unrecoverable_global_store_is_never_replaced_by_import(stores):
    store, legacy = stores
    Path(store.store_path).write_text("broken global store", encoding="utf-8")
    integration._migrate_legacy_task_stores(store)
    assert Path(store.store_path).read_text(encoding="utf-8") == "broken global store"
    assert legacy.exists()
    assert not integration._legacy_stores_migrated


def test_unreadable_legacy_source_remains_available_for_retry(stores):
    store, legacy = stores
    legacy.write_text("broken legacy store", encoding="utf-8")
    backup = Path(str(legacy) + ".bak")
    if backup.exists():
        backup.unlink()
    integration._migrate_legacy_task_stores(store)
    assert legacy.read_text(encoding="utf-8") == "broken legacy store"
    assert not Path(str(legacy) + ".migrated").exists()
    assert not integration._legacy_stores_migrated


def test_duplicate_global_id_keeps_its_existing_task(stores):
    store, legacy = stores
    store.add_task({"id": "reminder", "name": "Already imported", "agent_id": "primary"})
    integration._migrate_legacy_task_stores(store)
    assert TaskStore(store.store_path).get_task("reminder")["name"] == "Already imported"
    assert not legacy.exists()
    assert json.loads(Path(str(legacy) + ".migrated").read_text())["tasks"]["reminder"]["name"] == "Review the draft"
