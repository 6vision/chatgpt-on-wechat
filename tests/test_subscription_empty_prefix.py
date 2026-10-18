import pytest
import config


@pytest.mark.parametrize("prefixes", [[], None])
def test_empty_prefixes_do_not_break_subscription(monkeypatch, prefixes):
    monkeypatch.setattr(config, "config", {"single_chat_prefix": prefixes, "subscribe_msg": "Welcome {trigger_prefix}"})
    assert config.subscribe_msg() == "Welcome "


def test_configured_prefix_preserved(monkeypatch):
    monkeypatch.setattr(
        config, "config", {"single_chat_prefix": ["cow", "other"], "subscribe_msg": "Type {trigger_prefix}"}
    )
    assert config.subscribe_msg() == "Type cow"


def test_missing_prefix_preserved(monkeypatch):
    monkeypatch.setattr(config, "config", {"subscribe_msg": "Welcome {trigger_prefix}"})
    assert config.subscribe_msg() == "Welcome "
