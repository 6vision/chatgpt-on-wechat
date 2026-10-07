import json

import pytest

from agent.tools.scheduler.scheduler_tool import SchedulerTool
from agent.tools.scheduler.task_store import TaskStore
from bridge.context import Context


@pytest.mark.parametrize("path", ["tasks.json", "./tasks.json", "nested/tasks.json"])
def test_public_scheduler_with_relative_store(tmp_path, monkeypatch, path):
    monkeypatch.chdir(tmp_path)
    store = TaskStore(path)
    tool = SchedulerTool({"channel_type": "web"})
    tool.task_store = store
    tool.current_context = Context(kwargs={"channel_type": "web", "receiver": "owned-local", "session_id": "owned-session"})
    result = tool.execute({"action": "create", "name": "owned reminder", "message": "local only", "schedule_type": "interval", "schedule_value": "300"})
    assert result.status == "success"
    tasks = TaskStore(path).load_tasks()
    assert len(tasks) == 1
    task = next(iter(tasks.values()))
    assert task["name"] == "owned reminder" and task["schedule"] == {"type": "interval", "seconds": 300}
    assert json.loads((tmp_path / path).read_text())["tasks"] == tasks
