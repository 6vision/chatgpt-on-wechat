"""A scheduled task's delivery identity must come from the trusted directory."""

import json
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import patch

from agent.tools.scheduler.recipient_store import RecipientStore
from agent.tools.scheduler.task_store import TaskStore

# Keep this unit test independent from the optional web.py dependency, the same
# way tests/test_scheduler_web_update.py does.
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
    web_stub.application = lambda *a, **k: types.SimpleNamespace(wsgifunc=lambda: None)
    web_stub.httpserver = types.SimpleNamespace(
        LogMiddleware=type("LogMiddleware", (), {"log": lambda *a, **k: None}),
        StaticMiddleware=lambda app: app,
        WSGIServer=lambda *a, **k: types.SimpleNamespace(serve_forever=lambda: None),
    )
    sys.modules["web"] = web_stub

from channel.web.api import scheduler as scheduler_api


VICTIM = {
    "channel_type": "feishu",
    "instance_id": "feishu",
    "receiver": "ou_victim_openid",
    "name": "Victim",
    "session_id": "session-of-victim",
    "is_group": False,
}


def _action(**overrides):
    action = {
        "type": "send_message",
        "channel_type": VICTIM["channel_type"],
        "instance_id": VICTIM["instance_id"],
        "receiver": VICTIM["receiver"],
        "receiver_name": VICTIM["name"],
        "is_group": VICTIM["is_group"],
        "notify_session_id": VICTIM["session_id"],
        "content": "daily standup",
    }
    action.update(overrides)
    return action


def _store(tmp_path, action):
    store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    store.add_task(
        {
            "id": "task-1",
            "name": "maintenance",
            "enabled": True,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "next_run_at": (datetime.now() + timedelta(hours=1)).isoformat(),
            "schedule": {"type": "interval", "seconds": 3600},
            "action": action,
        }
    )
    return store


def _post(store, payload, recipients=None):
    """POST the update handler and return the response body."""
    target = recipients if recipients is not None else RecipientStore(str(
        store.path.parent / "recipients.json"
    ))
    with patch("channel.web.api.scheduler._require_auth"), patch(
        "channel.web.api.scheduler.web.header"
    ), patch(
        "channel.web.api.scheduler.web.data",
        return_value=json.dumps({"task_id": "task-1", **payload}).encode(),
    ), patch(
        "channel.web.api.scheduler._global_task_store", return_value=store
    ), patch(
        "agent.tools.scheduler.integration.get_recipient_store", return_value=target
    ):
        return json.loads(scheduler_api.SchedulerUpdateHandler().POST())


def _remember(recipients, entry=VICTIM):
    recipients.remember(
        entry["instance_id"],
        entry["receiver"],
        name=entry["name"],
        session_id=entry["session_id"],
        is_group=entry["is_group"],
    )


def _stored(tmp_path):
    store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    return store.get_task("task-1")["action"]


# --- the gap ----------------------------------------------------------------


def test_a_foreign_notify_session_id_does_not_survive_an_unrelated_edit(tmp_path):
    recipients = RecipientStore(str(tmp_path / "recipients.json"))
    _remember(recipients)
    store = _store(tmp_path, _action())

    # The user edits the text and swaps who the output is written into, leaving
    # channel / instance / receiver untouched.
    response = _post(
        store,
        {
            "action": {
                "notify_session_id": "session-of-someone-else-entirely",
                "receiver_name": "Totally Different Person",
                "is_group": True,
            }
        },
        recipients,
    )

    assert response.get("status") != "error", response
    stored = _stored(tmp_path)
    assert stored["notify_session_id"] == VICTIM["session_id"]
    assert stored["receiver_name"] == VICTIM["name"]
    assert stored["is_group"] is False


def test_the_directory_is_consulted_even_when_the_target_is_unchanged(tmp_path):
    recipients = RecipientStore(str(tmp_path / "recipients.json"))
    _remember(recipients)
    store = _store(tmp_path, _action())
    seen = []
    original_get = recipients.get

    def spy(instance_id, receiver):
        seen.append((instance_id, receiver))
        return original_get(instance_id, receiver)

    recipients.get = spy

    _post(store, {"action": {"notify_session_id": "someone-elses"}}, recipients)

    assert seen == [(VICTIM["instance_id"], VICTIM["receiver"])]


# --- the rules that already worked -----------------------------------------


def test_repointing_at_an_untrusted_recipient_is_still_refused(tmp_path):
    recipients = RecipientStore(str(tmp_path / "recipients.json"))
    _remember(recipients)
    store = _store(tmp_path, _action())

    response = _post(
        store,
        {"action": {"channel_type": "feishu", "instance_id": "feishu",
                    "receiver": "ou_stranger"}},
        recipients,
    )

    assert response["status"] == "error"
    assert "trusted directory" in response["message"]
    assert _stored(tmp_path)["receiver"] == VICTIM["receiver"]


def test_repointing_at_another_trusted_recipient_rewrites_every_field(tmp_path):
    recipients = RecipientStore(str(tmp_path / "recipients.json"))
    _remember(recipients)
    _remember(
        recipients,
        {
            "channel_type": "wecom_bot",
            "instance_id": "wecom_bot",
            "receiver": "user-9",
            "name": "Grace",
            "session_id": "session-9",
            "is_group": True,
        },
    )
    store = _store(tmp_path, _action())

    response = _post(
        store,
        {"action": {"channel_type": "wecom_bot", "instance_id": "wecom_bot",
                    "receiver": "user-9"}},
        recipients,
    )

    assert response.get("status") != "error", response
    stored = _stored(tmp_path)
    assert stored["channel_type"] == "wecom_bot"
    assert stored["receiver"] == "user-9"
    assert stored["receiver_name"] == "Grace"
    assert stored["notify_session_id"] == "session-9"
    assert stored["is_group"] is True


def test_an_identity_only_edit_still_persists_the_text(tmp_path):
    recipients = RecipientStore(str(tmp_path / "recipients.json"))
    _remember(recipients)
    store = _store(tmp_path, _action())

    _post(store, {"action": {"content": "weekly report"}}, recipients)

    stored = _stored(tmp_path)
    assert stored["content"] == "weekly report"
    assert stored["notify_session_id"] == VICTIM["session_id"]


def test_a_web_task_never_reaches_the_directory(tmp_path):
    # Web tasks are frozen by the branch above, so their identity is whatever
    # was stored at creation time.
    recipients = RecipientStore(str(tmp_path / "recipients.json"))
    _remember(recipients)
    store = _store(
        tmp_path, _action(channel_type="web", notify_session_id="web-session")
    )

    response = _post(store, {"action": {"content": "note"}}, recipients)

    assert response.get("status") != "error", response
    assert _stored(tmp_path)["notify_session_id"] == "web-session"


def test_switching_a_web_task_to_an_im_channel_is_refused(tmp_path):
    recipients = RecipientStore(str(tmp_path / "recipients.json"))
    _remember(recipients)
    store = _store(
        tmp_path, _action(channel_type="web", notify_session_id="web-session")
    )

    response = _post(store, {"action": {"channel_type": "feishu"}}, recipients)

    assert response["status"] == "error"
    assert "Cannot change channel type" in response["message"]


def test_a_recipient_no_longer_in_the_directory_is_still_editable(tmp_path):
    # A recipient can leave the directory while a task still points at it.
    # Refusing the edit would leave the user unable to even rename the task, so
    # the stored identity is kept instead -- what matters is that the body still
    # does not get to choose it.
    recipients = RecipientStore(str(tmp_path / "recipients.json"))
    store = _store(tmp_path, _action())

    response = _post(
        store,
        {
            "name": "renamed",
            "action": {"notify_session_id": "session-attacker", "content": "edited"},
        },
        recipients,
    )

    assert response["status"] == "success", response
    stored = _stored(tmp_path)
    assert stored["notify_session_id"] == VICTIM["session_id"]
    assert stored["receiver"] == VICTIM["receiver"]
    assert stored["content"] == "edited"


def test_the_stored_action_never_keeps_a_body_supplied_identity(tmp_path):
    # The whole point, stated once more over every identity field: whatever the
    # body said, the directory decides.
    recipients = RecipientStore(str(tmp_path / "recipients.json"))
    _remember(recipients)
    store = _store(tmp_path, _action())

    _post(
        store,
        {
            "action": {
                "notify_session_id": "session-attacker",
                "receiver_name": "Attacker",
                "is_group": True,
                "content": "still just an edit",
            }
        },
        recipients,
    )

    stored = _stored(tmp_path)
    assert {stored["notify_session_id"], stored["receiver_name"]} == {
        VICTIM["session_id"],
        VICTIM["name"],
    }
    assert stored["is_group"] is VICTIM["is_group"]
    assert stored["content"] == "still just an edit"
