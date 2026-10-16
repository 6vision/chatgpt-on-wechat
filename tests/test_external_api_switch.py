"""The chat API's switch: turning it off keeps the key."""

import json

import pytest

from channel.web.api import config as config_api


@pytest.fixture
def console(monkeypatch, tmp_path):
    live = {}
    saved = {}
    monkeypatch.setattr(config_api, "conf", lambda: live)
    monkeypatch.setattr(config_api, "_require_auth", lambda: None)
    monkeypatch.setattr(config_api, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(config_api, "_read_config_file_for_write", lambda: dict(saved))
    monkeypatch.setattr(
        config_api, "_write_config_file_for_write", lambda path, cfg: saved.update(cfg)
    )
    monkeypatch.setattr(config_api.web, "header", lambda *a, **k: None)

    def post(action):
        monkeypatch.setattr(config_api.web, "data", lambda: json.dumps({"action": action}).encode())
        return json.loads(config_api.ExternalApiHandler().POST())

    return post, live, saved


def test_off_keeps_the_key_and_on_reuses_it(console):
    post, live, saved = console

    first = post("enable")
    assert first["enabled"] is True
    assert first["api_key"].startswith("sk-cow-")
    assert saved == {"external_api_enabled": True, "external_api_token": first["api_key"]}

    off = post("disable")
    assert off["enabled"] is False
    assert saved["external_api_token"] == first["api_key"]
    assert live["external_api_enabled"] is False

    again = post("enable")
    assert again["api_key"] == first["api_key"]


def test_regenerate_replaces_the_key_and_leaves_the_switch(console):
    post, live, saved = console
    first = post("enable")

    renewed = post("regenerate")
    assert renewed["enabled"] is True
    assert renewed["api_key"] != first["api_key"]
    assert saved["external_api_token"] == renewed["api_key"]
