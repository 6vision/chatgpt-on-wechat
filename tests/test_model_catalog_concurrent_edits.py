"""Catalog read-modify-write and cache fills must form one serialized operation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread

import pytest

from models import model_catalog


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(model_catalog, "_store_path", lambda: str(tmp_path / "models.json"))
    model_catalog._invalidate()
    yield
    model_catalog._invalidate()


def test_concurrent_provider_saves_retain_both_edits(catalog, monkeypatch):
    first_writing, release_first, second_read = Event(), Event(), Event()
    read_store, write_store = model_catalog._read_store, model_catalog._write_store

    def observed_read():
        store = read_store()
        if current_thread().name.startswith("second"):
            second_read.set()
        return store

    def paused_write(store):
        if set(store["providers"]) == {"first"}:
            first_writing.set()
            assert release_first.wait(3)
        write_store(store)

    monkeypatch.setattr(model_catalog, "_read_store", observed_read)
    monkeypatch.setattr(model_catalog, "_write_store", paused_write)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="first") as first, ThreadPoolExecutor(max_workers=1, thread_name_prefix="second") as second:
        a = first.submit(model_catalog.save_catalog, "first", [{"name": "alpha"}])
        assert first_writing.wait(3)
        b = second.submit(model_catalog.save_catalog, "second", [{"name": "beta"}])
        # On the fixed code the second read waits for the transaction lock.
        # The bound releases the first writer without requiring that read.
        second_read.wait(0.25)
        release_first.set()
        a.result(timeout=3)
        b.result(timeout=3)
    assert set(model_catalog.get_catalog_map()) == {"first", "second"}


def test_cache_fill_cannot_publish_snapshot_after_save_invalidates_it(catalog, monkeypatch):
    model_catalog.save_catalog("old", [{"name": "existing"}])
    model_catalog._invalidate()
    snapshot_read, release_reader, save_done = Event(), Event(), Event()
    read_store = model_catalog._read_store

    def paused_read():
        store = read_store()
        if current_thread().name.startswith("reader"):
            snapshot_read.set()
            assert release_reader.wait(3)
        return store

    def save():
        model_catalog.save_catalog("new", [{"name": "new-model"}])
        save_done.set()

    monkeypatch.setattr(model_catalog, "_read_store", paused_read)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="reader") as reader, ThreadPoolExecutor(max_workers=1, thread_name_prefix="writer") as writer:
        a = reader.submit(model_catalog.get_catalog_map)
        assert snapshot_read.wait(3)
        b = writer.submit(save)
        save_done.wait(0.25)
        release_reader.set()
        a.result(timeout=3)
        b.result(timeout=3)
    assert set(model_catalog.get_catalog_map()) == {"old", "new"}
