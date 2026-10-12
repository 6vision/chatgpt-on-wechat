import json
from agent.tools.scheduler.task_store import TaskStore


def test_missing_primary_recovers_existing_backup_before_mutation(tmp_path):
    primary = tmp_path / "tasks.json"
    backup = tmp_path / "tasks.json.bak"
    backup.write_text(
        json.dumps({"version": 1, "tasks": {"old": {"id": "old", "name": "retained schedule"}}}), encoding="utf-8"
    )
    store = TaskStore(str(primary))
    assert "old" in store.load_tasks()
    store.add_task({"id": "new"})
    assert set(store.load_tasks()) == {"old", "new"}
    assert "old" in json.loads(backup.read_text())["tasks"]


def test_new_store_without_backup_is_empty(tmp_path):
    store = TaskStore(str(tmp_path / "tasks.json"))
    assert store.load_tasks() == {}
    store.add_task({"id": "first"})
    assert set(store.load_tasks()) == {"first"}
