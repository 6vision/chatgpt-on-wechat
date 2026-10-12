# encoding:utf-8
"""Toggling a task that does not exist must say so.

``SchedulerToggleHandler`` enabled the task, read it back and reported success
without ever checking that it was there. A typo'd or already-deleted task id
therefore produced ``{"status": "success", "task": null}`` -- a success toast
in the console for a change that changed nothing, and a ``null`` for any client
that reads the task back. ``SchedulerUpdateHandler`` already returns
"Task '<id>' not found" for the same situation.
"""

import json

import pytest

from channel.web.api import scheduler as scheduler_api


class FakeStore:
    def __init__(self, tasks):
        self._tasks = dict(tasks)
        self.enabled_calls = []

    def get_task(self, task_id):
        return self._tasks.get(task_id)

    def enable_task(self, task_id, enabled):
        self.enabled_calls.append((task_id, enabled))
        task = self._tasks.get(task_id)
        if task is not None:
            task["enabled"] = enabled
        return task


def _post(monkeypatch, body, store):
    import web

    monkeypatch.setattr(scheduler_api, "_require_auth", lambda: None)
    monkeypatch.setattr(scheduler_api, "_global_task_store", lambda: store)
    monkeypatch.setattr(web, "header", lambda *a, **k: None)
    monkeypatch.setattr(web, "data", lambda: json.dumps(body).encode("utf-8"))
    return json.loads(scheduler_api.SchedulerToggleHandler().POST())


def test_toggling_a_missing_task_reports_an_error(monkeypatch):
    store = FakeStore({"other": {"id": "other", "enabled": False}})

    result = _post(monkeypatch, {"task_id": "does-not-exist", "enabled": True}, store)

    assert result["status"] == "error", result
    assert "does-not-exist" in result["message"]
    assert store.enabled_calls == [], "enable_task ran for a task that does not exist"


def test_toggling_an_existing_task_reports_success(monkeypatch):
    store = FakeStore({"t1": {"id": "t1", "enabled": False}})

    result = _post(monkeypatch, {"task_id": "t1", "enabled": True}, store)

    assert result["status"] == "success", result
    assert result["task"]["enabled"] is True
    assert store.enabled_calls == [("t1", True)]


def test_disabling_an_existing_task_reports_success(monkeypatch):
    store = FakeStore({"t1": {"id": "t1", "enabled": True}})

    result = _post(monkeypatch, {"task_id": "t1", "enabled": False}, store)

    assert result["status"] == "success", result
    assert result["task"]["enabled"] is False


@pytest.mark.parametrize("body", [{}, {"task_id": ""}, {"task_id": None}])
def test_a_missing_task_id_is_still_rejected(monkeypatch, body):
    store = FakeStore({"t1": {"id": "t1", "enabled": False}})

    result = _post(monkeypatch, body, store)

    assert result["status"] == "error", result
    assert store.enabled_calls == []
