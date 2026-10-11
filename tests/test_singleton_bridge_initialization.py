"""Concurrent cold Bridge callers must share its singleton instance."""

import threading

import pytest

import bridge.bridge as bridge_module
from common.singleton import singleton


SETTINGS = {"voice_to_text": "openai", "text_to_voice": "google", "model": "gpt-4"}


def test_concurrent_cold_bridge_calls_share_one_instance(monkeypatch):
    # Use the production Bridge constructor with an isolated decorator cache.
    # No model/provider is created; conf is pinned to synthetic settings.
    bridge = singleton(bridge_module.Bridge.__wrapped__)
    entered = threading.Event()
    release = threading.Event()
    another_conf = threading.Event()
    lock = threading.Lock()
    calls = 0
    instances = []
    errors = []

    def settings():
        nonlocal calls
        with lock:
            calls += 1
            first = calls == 1
        if first:
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Fixture constructor was not released")
        else:
            another_conf.set()
        return SETTINGS

    def create():
        try:
            instances.append(bridge())
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(bridge_module, "conf", settings)
    first = threading.Thread(target=create)
    second = threading.Thread(target=create)
    try:
        first.start()
        assert entered.wait(2)
        second.start()
        another_conf.wait(0.2)
    finally:
        release.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    assert len(instances) == 2
    assert instances[0] is instances[1]
    assert bridge() is instances[0]


def test_explicit_new_bridge_instances_stay_uncached(monkeypatch):
    monkeypatch.setattr(bridge_module, "conf", lambda: SETTINGS)
    bridge = singleton(bridge_module.Bridge.__wrapped__)
    cached = bridge()
    fresh = bridge.new_instance()
    assert fresh is not cached
    assert bridge() is cached
    assert bridge.__wrapped__ is bridge_module.Bridge.__wrapped__


def test_failed_bridge_initialization_can_retry(monkeypatch):
    bridge = singleton(bridge_module.Bridge.__wrapped__)

    def failed_settings():
        raise RuntimeError("fixture settings failure")

    monkeypatch.setattr(bridge_module, "conf", failed_settings)
    with pytest.raises(RuntimeError, match="fixture settings failure"):
        bridge()
    monkeypatch.setattr(bridge_module, "conf", lambda: SETTINGS)
    instance = bridge()
    assert bridge() is instance
