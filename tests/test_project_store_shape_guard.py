"""A malformed ``projects.json`` costs the bindings, not the feature.

``project_store`` and ``session_prefs`` are siblings: same key scheme, same
atomic write, same "read falls back to config.json" story. They differ in how
they treat a file that parses but holds the wrong shape.

``session_prefs._load`` checks it::

    if not isinstance(data.get("sessions"), dict):
        data["sessions"] = {}

``project_store._load`` only ``setdefault``s — which fills a key that is
*absent* and leaves a present one alone whatever its type. So a file carrying
``"sessions": []`` keeps the list, and every caller then calls ``.get()``,
``.pop()`` or ``.items()`` on it:

    get_project_map     ValueError: dictionary update sequence element #0 ...
    get_project_dir     AttributeError: 'list' object has no attribute 'get'
    delete_project      AttributeError: 'list' object has no attribute 'items'
    forget_session      TypeError: pop expected at most 1 argument, got 2
    set_project_dir     TypeError: list indices must be integers or slices

The last two matter most: they are the two calls that would repair the file, so
a bad shape also takes away the way out. The project picker's GET catches the
exception and answers ``{"status": "error"}``, which leaves the user with no
project selector and no session grouping until the JSON is fixed by hand.

These tests write the bad shapes and read the store back.
"""

import json
import os

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A project_store whose file lives in tmp_path, with a helper to poison it."""
    import common.state_dir as state_dir

    monkeypatch.setattr(state_dir, "shared_root", lambda *a, **k: tmp_path)

    from agent.workspace import project_store

    def poison(payload):
        path = project_store._store_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def on_disk():
        path = project_store._store_file()
        if not os.path.isfile(path):
            return None
        try:
            return json.loads(open(path, encoding="utf-8").read())
        except ValueError:
            return "unparseable"

    return project_store, poison, on_disk


BAD_SESSIONS = [
    pytest.param(["oops"], id="list"),
    pytest.param("oops", id="string"),
    pytest.param(7, id="number"),
    pytest.param(None, id="null"),
]


@pytest.mark.parametrize("bad", BAD_SESSIONS)
def test_reading_a_session_survives_a_bad_shape(store, bad):
    project_store, poison, _on_disk = store
    poison({"sessions": bad, "recents": [], "meta": {}, "order": []})

    # Both reads the session list makes.
    assert project_store.get_project_map("research") == {}
    assert project_store.get_project_dir("s1", "research") is None


def test_forgetting_a_session_survives_a_bad_shape(store, tmp_path):
    """This is the call that would repair the file, so it must not raise."""
    project_store, poison, on_disk = store
    project = tmp_path / "proj"
    project.mkdir()
    poison({"sessions": ["oops"], "recents": [], "meta": {}, "order": []})

    project_store.forget_session("s1", agent_id="research")

    # Nothing was bound under that key, so nothing is written — the existing
    # "only save when a row actually went away" behaviour, kept as it is. What
    # matters is that the call returns instead of raising on the bad shape.
    assert on_disk()["sessions"] == ["oops"]

    # A row that *is* there goes away, and the file is rewritten without it.
    project_store.set_project_dir("s1", str(project), agent_id="research")
    assert list(on_disk()["sessions"]) == ["research::s1"]

    project_store.forget_session("s1", agent_id="research")
    assert on_disk()["sessions"] == {}


def test_binding_a_session_survives_a_bad_shape(store, tmp_path):
    project_store, poison, on_disk = store
    project = tmp_path / "proj"
    project.mkdir()
    poison({"sessions": ["oops"], "recents": [], "meta": {}, "order": []})

    project_store.set_project_dir("s1", str(project), agent_id="research")

    assert list(on_disk()["sessions"]) == ["research::s1"]
    # And the binding is readable, not just stored.
    assert project_store.get_project_dir("s1", "research") is not None


def test_sweeping_an_agent_survives_a_bad_shape(store):
    project_store, poison, _on_disk = store
    poison({"sessions": ["oops"], "recents": [], "meta": {}, "order": []})

    project_store.forget_agent("research")

    assert project_store.get_project_map("research") == {}


def test_deleting_a_project_survives_a_bad_shape(store, tmp_path):
    project_store, poison, on_disk = store
    project = tmp_path / "proj"
    project.mkdir()
    real = str(project)
    poison({"sessions": ["oops"], "recents": [{"path": real}], "meta": {}, "order": []})

    project_store.delete_project(real, agent_id="research")

    assert on_disk()["sessions"] == {}
    assert on_disk()["recents"] == []


@pytest.mark.parametrize(
    "key,bad", [("recents", {}), ("meta", []), ("order", "oops")]
)
def test_a_bad_shape_anywhere_is_replaced(store, key, bad):
    project_store, poison, _on_disk = store
    payload = {"sessions": {}, "recents": [], "meta": {}, "order": []}
    payload[key] = bad
    poison(payload)

    project_store.get_project_map("research")
    project_store.list_recents()
    project_store.get_order()

    # And the store is usable afterwards: a write lands normally.
    project = project_store.projects_root()
    os.makedirs(project, exist_ok=True)
    created = project_store.create_project("fresh")
    assert os.path.isdir(created)


def test_a_file_holding_a_list_rather_than_an_object_is_survivable(store):
    project_store, poison, on_disk = store
    poison(["not", "an", "object"])

    assert project_store.get_project_map("research") == {}
    assert project_store.list_recents() == []

    # A write lands normally afterwards. set_order normalises every entry that
    # is not the default sentinel, so compare against the normalised form.
    project_store.set_order(["a", "b"])
    stored = on_disk()["order"]
    assert len(stored) == 2
    assert all(os.path.isabs(entry) for entry in stored)


def test_a_well_formed_file_is_untouched(store, tmp_path):
    """The guard must not rewrite a good file behind the user's back."""
    project_store, poison, on_disk = store
    project = tmp_path / "proj"
    project.mkdir()
    poison(
        {
            "sessions": {"research::s1": {"path": str(project), "ts": 1.0}},
            "recents": [{"path": str(project), "name": "proj", "ts": 2.0}],
            "meta": {str(project): {"display_name": "My project"}},
            "order": [str(project)],
        }
    )
    before = on_disk()

    assert project_store.get_project_map("research") == {"s1": str(project)}
    assert project_store.display_name_for(str(project)) == "My project"
    assert project_store.get_order() == [str(project)]
    assert on_disk() == before


def test_a_missing_file_still_yields_an_empty_store(store):
    project_store, _poison, on_disk = store

    assert on_disk() is None
    assert project_store.get_project_map("research") == {}
    assert project_store.list_recents() == []
    assert project_store.get_order() == []


def test_unparseable_json_is_still_a_warning_not_a_crash(store):
    project_store, _poison, on_disk = store
    path = project_store._store_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{not json")

    # The store answers with an empty roster and leaves the file for the user
    # to look at, rather than guessing.
    assert project_store.get_project_map("research") == {}
    assert project_store.list_recents() == []
    assert project_store.get_order() == []
    # The bad file is left exactly as it was, not silently rewritten.
    assert on_disk() == "unparseable"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
