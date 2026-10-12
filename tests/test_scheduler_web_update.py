"""Regression tests for scheduler edits made through the Web console."""

import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from agent.tools.scheduler.task_store import TaskStore

# Keep this unit test independent from the optional web.py dependency.
if "web" not in sys.modules:
    web_stub = types.ModuleType("web")
    web_stub.HTTPError = type("HTTPError", (Exception,), {})
    web_stub.cookies = lambda: {}
    web_stub.header = lambda *args, **kwargs: None
    web_stub.data = lambda: b"{}"
    web_stub.input = lambda **kwargs: types.SimpleNamespace(**kwargs)
    web_stub.setcookie = lambda *args, **kwargs: None
    web_stub.seeother = lambda *args, **kwargs: Exception("seeother")
    web_stub.notfound = lambda *args, **kwargs: Exception("notfound")
    web_stub.badrequest = lambda *args, **kwargs: Exception("badrequest")
    web_stub.application = lambda *args, **kwargs: types.SimpleNamespace(wsgifunc=lambda: None)
    web_stub.httpserver = types.SimpleNamespace(
        LogMiddleware=type("LogMiddleware", (), {"log": lambda *args, **kwargs: None}),
        StaticMiddleware=lambda app: app,
        WSGIServer=lambda *args, **kwargs: types.SimpleNamespace(serve_forever=lambda: None),
    )
    sys.modules["web"] = web_stub

from channel.web.api import scheduler as scheduler_api

SchedulerUpdateHandler = scheduler_api.SchedulerUpdateHandler


def _store_task(tmp_path, action):
    store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    store.add_task({
        "id": "task-1",
        "name": "maintenance",
        "enabled": True,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "next_run_at": (datetime.now() + timedelta(hours=1)).isoformat(),
        "schedule": {"type": "interval", "seconds": 3600},
        "action": action,
    })
    return store


def _post_update(store, payload):
    with patch("channel.web.api.scheduler._require_auth"), \
         patch("channel.web.api.scheduler.web.header"), \
         patch("channel.web.api.scheduler.web.data", return_value=json.dumps(payload).encode()), \
         patch("channel.web.api.scheduler._global_task_store", return_value=store):
        return json.loads(SchedulerUpdateHandler().POST())


def test_web_manual_run_is_authenticated_and_delegates_to_scheduler():
    assert hasattr(scheduler_api, "SchedulerRunHandler")

    service = Mock()
    with patch("channel.web.api.scheduler._require_auth") as require_auth, \
         patch("channel.web.api.scheduler.web.header"), \
         patch("channel.web.api.scheduler.web.data", return_value=b'{"task_id":"task-1"}'), \
         patch("agent.tools.scheduler.integration.get_scheduler_service", return_value=service):
        response = json.loads(scheduler_api.SchedulerRunHandler().POST())

    require_auth.assert_called_once_with()
    service.run_task_now.assert_called_once_with("task-1")
    assert response == {
        "status": "success",
        "message": "Task 'task-1' queued for immediate execution",
    }


def test_web_manual_run_rejects_unavailable_scheduler():
    assert hasattr(scheduler_api, "SchedulerRunHandler")

    with patch("channel.web.api.scheduler._require_auth"), \
         patch("channel.web.api.scheduler.web.header"), \
         patch("channel.web.api.scheduler.web.data", return_value=b'{"task_id":"task-1"}'), \
         patch("agent.tools.scheduler.integration.get_scheduler_service", return_value=None):
        response = json.loads(scheduler_api.SchedulerRunHandler().POST())

    assert response == {
        "status": "error",
        "message": "Scheduler service is not running",
    }


def test_manual_run_is_exposed_by_explicit_web_and_desktop_controls():
    root = Path(__file__).parents[1]
    from conftest import console_js, web_backend_py
    web_source = web_backend_py()
    web_console = console_js()
    desktop_client = (root / "desktop/src/renderer/src/api/client.ts").read_text(encoding="utf-8")
    desktop_page = (root / "desktop/src/renderer/src/pages/TasksPage.tsx").read_text(encoding="utf-8")

    assert "'/api/scheduler/run', 'SchedulerRunHandler'" in web_source
    assert "function runTaskNow(task, button)" in web_console
    assert "fetch('/api/scheduler/run'" in web_console
    web_run = web_console[web_console.index("function runTaskNow(task, button)"):]
    assert "showConfirmDialog({" in web_run[:2500]
    assert "async runTask(taskId: string" in desktop_client
    assert "'/api/scheduler/run'" in desktop_client
    assert "const runNow = async ()" in desktop_page
    # Desktop confirms via the app's custom dialog (askConfirm), matching the web
    # console's showConfirmDialog rather than a native window.confirm.
    assert "askConfirm({ titleKey: 'task_run_now'" in desktop_page


def test_web_edit_preserves_hidden_agent_action_fields(tmp_path):
    store = _store_task(tmp_path, {
        "type": "agent_task",
        "task_description": "refresh the index",
        "receiver": "user-1",
        "receiver_name": "User",
        "is_group": False,
        "channel_type": "feishu",
        "notify_session_id": "session-1",
        "silent": True,
        "delivery_extension": {"trace": True},
    })

    result = _post_update(store, {
        "task_id": "task-1",
        "name": "renamed maintenance",
        "action": {
            "type": "agent_task",
            "task_description": "refresh both indexes",
            "receiver": "user-1",
            "channel_type": "feishu",
        },
    })

    assert result["status"] == "success"
    action = store.get_task("task-1")["action"]
    assert action["task_description"] == "refresh both indexes"
    assert action["silent"] is True
    assert action["notify_session_id"] == "session-1"
    assert action["delivery_extension"] == {"trace": True}


def test_switch_to_message_drops_agent_only_fields(tmp_path):
    store = _store_task(tmp_path, {
        "type": "agent_task",
        "task_description": "refresh the index",
        "receiver": "user-1",
        "channel_type": "web",
        "notify_session_id": "session-1",
        "silent": True,
    })

    result = _post_update(store, {
        "task_id": "task-1",
        "action": {
            "type": "send_message",
            "content": "Index refresh reminder",
            "receiver": "user-1",
            "channel_type": "web",
        },
    })

    assert result["status"] == "success"
    action = store.get_task("task-1")["action"]
    assert action["content"] == "Index refresh reminder"
    assert "task_description" not in action
    assert "silent" not in action
    assert action["notify_session_id"] == "session-1"


def _seed_global_tasks(dir_path, items):
    store = TaskStore(str(dir_path / "scheduler" / "tasks.json"))
    for task_id, agent_id in items:
        store.add_task({
            "id": task_id,
            "name": task_id,
            "agent_id": agent_id,
            "enabled": True,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "schedule": {"type": "interval", "seconds": 3600},
            "action": {"type": "agent_task", "task_description": "x"},
        })
    return store


def test_list_aggregates_every_agent_and_tags_the_owner(tmp_path):
    """Without an explicit agent_id the list spans the whole team; each task
    carries the ``agent_id`` stored on the row, not implied by a file path."""
    store = _seed_global_tasks(tmp_path, [("p-task", "primary"), ("r-task", "research")])

    with patch("channel.web.api.scheduler._require_auth"), \
         patch("channel.web.api.scheduler.web.header"), \
         patch("channel.web.api.scheduler.web.input", return_value=types.SimpleNamespace(agent_id="")), \
         patch("channel.web.api.scheduler._global_task_store", return_value=store):
        response = json.loads(scheduler_api.SchedulerHandler().GET())

    assert response["status"] == "success"
    owners = {task["id"]: task["agent_id"] for task in response["tasks"]}
    assert owners == {"p-task": "primary", "r-task": "research"}


def test_list_scopes_to_a_single_agent_when_asked(tmp_path):
    store = _seed_global_tasks(tmp_path, [("p-task", "primary"), ("r-task", "research")])

    with patch("channel.web.api.scheduler._require_auth"), \
         patch("channel.web.api.scheduler.web.header"), \
         patch("channel.web.api.scheduler.web.input", return_value=types.SimpleNamespace(agent_id="research")), \
         patch("channel.web.api.scheduler._request_agent_id", return_value="research"), \
         patch("channel.web.api.scheduler._global_task_store", return_value=store):
        response = json.loads(scheduler_api.SchedulerHandler().GET())

    assert response["status"] == "success"
    assert [task["id"] for task in response["tasks"]] == ["r-task"]
    assert response["tasks"][0]["agent_id"] == "research"


# ---------------------------------------------------------------------------
# The action type is part of what a user may create, so it is part of what a
# user may edit into. The scheduler can run `tool_call` / `skill_call` for a
# task some other code path built, but reaching those through the console would
# run a registered tool on a timer outside the agent's tool-calling path -- and
# therefore outside `check_tool_call`, so the session's permission mode would
# not apply and nothing would reach its audit.
# ---------------------------------------------------------------------------

_UNSAFE_TYPES = ("tool_call", "skill_call")


def test_create_and_update_agree_on_the_action_type_whitelist():
    assert scheduler_api._ALLOWED_ACTION_TYPES == ("send_message", "agent_task")
    for action_type in _UNSAFE_TYPES:
        assert action_type not in scheduler_api._ALLOWED_ACTION_TYPES


def test_switching_to_a_tool_call_is_refused(tmp_path):
    store = _store_task(tmp_path, {
        "type": "send_message",
        "content": "daily digest",
        "receiver": "user-1",
        "channel_type": "web",
    })

    result = _post_update(store, {
        "task_id": "task-1",
        "action": {
            "type": "tool_call",
            "call_name": "bash",
            "call_params": {"command": "echo should-not-run"},
            "receiver": "user-1",
            "channel_type": "web",
        },
    })

    assert result["status"] == "error"
    assert "action type" in result["message"].lower()
    # The stored task is untouched, so nothing is left queued to run it.
    assert store.get_task("task-1")["action"]["type"] == "send_message"


def test_switching_to_a_skill_call_is_refused(tmp_path):
    store = _store_task(tmp_path, {
        "type": "send_message",
        "content": "daily digest",
        "receiver": "user-1",
        "channel_type": "web",
    })

    result = _post_update(store, {
        "task_id": "task-1",
        "action": {
            "type": "skill_call",
            "skill_name": "anything",
            "receiver": "user-1",
            "channel_type": "web",
        },
    })

    assert result["status"] == "error"
    assert store.get_task("task-1")["action"]["type"] == "send_message"


def test_a_refused_switch_does_not_smuggle_in_a_tool_name(tmp_path):
    """The whole action is rejected, not just the type field: leaving the tool
    fields in the stored action would be enough for the scheduler to run it."""
    store = _store_task(tmp_path, {
        "type": "agent_task",
        "task_description": "refresh the index",
        "receiver": "user-1",
        "channel_type": "web",
    })

    result = _post_update(store, {
        "task_id": "task-1",
        "action": {
            "type": "tool_call",
            "call_name": "bash",
            "call_params": {"command": "echo should-not-run"},
            "task_description": "refresh the index",
            "receiver": "user-1",
            "channel_type": "web",
        },
    })

    assert result["status"] == "error"
    action = store.get_task("task-1")["action"]
    assert "call_name" not in action
    assert "call_params" not in action


def test_the_two_supported_switches_still_work(tmp_path):
    """The control: the whitelist rejects nothing it used to allow."""
    for index, (target, stored_type, marker) in enumerate((
        ("send_message", "agent_task", "content"),
        ("agent_task", "send_message", "task_description"),
    )):
        # _store_task always uses "task-1", so each round needs its own store.
        store = _store_task(tmp_path / f"case{index}", {
            "type": stored_type,
            "receiver": "user-1",
            "channel_type": "web",
        })
        patch_body = {
            "type": target,
            "receiver": "user-1",
            "channel_type": "web",
            marker: "value-for-" + target,
        }
        result = _post_update(store, {"task_id": "task-1", "action": patch_body})

        assert result["status"] == "success", (target, result)
        assert store.get_task("task-1")["action"]["type"] == target
