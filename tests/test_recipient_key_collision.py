import json

from agent.tools.scheduler.recipient_store import RecipientStore


def test_colon_components_do_not_alias_another_contact(tmp_path):
    path = tmp_path / "recipients.json"
    store = RecipientStore(str(path))
    store.remember("weixin", "user", name="Ada", instance_id="bot:west")
    store.remember("weixin", "west:user", name="Bob", instance_id="bot")
    reopened = RecipientStore(str(path))
    assert reopened.get("bot:west", "user")["name"] == "Ada"
    assert reopened.get("bot", "west:user")["name"] == "Bob"
    assert len(reopened.list()) == 2


def test_legacy_colon_entry_is_not_returned_for_another_pair(tmp_path):
    path = tmp_path / "recipients.json"
    entry = {
        "channel_type": "weixin",
        "instance_id": "bot:west",
        "receiver": "user",
        "name": "Ada",
        "is_group": False,
        "session_id": "user",
        "last_seen_at": "2026-09-07T03:01:28+00:00",
    }
    path.write_text(json.dumps({"version": 1, "recipients": {"bot:west:user": entry}}))
    store = RecipientStore(str(path))
    assert store.get("bot:west", "user")["name"] == "Ada"
    assert store.get("bot", "west:user") is None
    store.remember("weixin", "west:user", name="Bob", instance_id="bot")
    assert store.get("bot:west", "user")["name"] == "Ada"
    assert len(store.list()) == 2


def test_percent_escape_is_itself_escaped(tmp_path):
    store = RecipientStore(str(tmp_path / "recipients.json"))
    store.remember("weixin", "user", name="Ada", instance_id="bot:west")
    store.remember("weixin", "user", name="Bob", instance_id="bot%3Awest")
    assert store.get("bot:west", "user")["name"] == "Ada"
    assert store.get("bot%3Awest", "user")["name"] == "Bob"
