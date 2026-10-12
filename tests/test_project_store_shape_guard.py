"""project_store tolerates a projects.json that parses but holds the wrong shape."""

import json
import os

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    import common.state_dir as state_dir

    monkeypatch.setattr(state_dir, "shared_root", lambda *a, **k: tmp_path)

    from agent.workspace import project_store

    path = project_store._store_file()

    def write(payload, raw=False):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload) if raw else json.dump(payload, handle)

    def on_disk():
        try:
            return json.loads(open(path, encoding="utf-8").read())
        except FileNotFoundError:
            return None
        except ValueError:
            return "unparseable"

    (tmp_path / "proj").mkdir()
    return project_store, write, on_disk, str(tmp_path / "proj")


def _shape(sessions=("oops",), recents=(), meta=None, order=()):
    return {"sessions": sessions, "recents": recents, "meta": {} if meta is None else meta, "order": order}


@pytest.mark.parametrize("payload", [
    _shape(["oops"]), _shape("oops"), _shape(7), _shape(None), _shape({}, recents={}), _shape({}, meta=[]),
    _shape({}, order="oops"), ["not", "an", "object"], None, "{not json",
], ids=["sessions-list", "sessions-str", "sessions-num", "sessions-null", "recents", "meta", "order",
        "top-list", "missing", "unparseable"])
def test_bad_or_missing_file_leaves_a_usable_store(store, payload):
    project_store, write, on_disk, _ = store
    if payload is not None:
        write(payload, raw=isinstance(payload, str))

    assert project_store.get_project_map("research") == {}
    assert project_store.get_project_dir("s1", "research") is None
    assert project_store.list_recents() == []
    assert project_store.get_order() == []
    if isinstance(payload, str):
        assert on_disk() == "unparseable", "an unparseable file must be left for the user"
    os.makedirs(project_store.projects_root(), exist_ok=True)
    assert os.path.isdir(project_store.create_project("fresh"))


def test_bind_and_forget_repair_bad_sessions(store):
    project_store, write, on_disk, project = store
    write(_shape())

    # Nothing bound under that key, so nothing is written.
    project_store.forget_session("s1", agent_id="research")
    assert on_disk()["sessions"] == ["oops"]

    project_store.set_project_dir("s1", project, agent_id="research")
    assert list(on_disk()["sessions"]) == ["research::s1"]
    assert project_store.get_project_dir("s1", "research") is not None

    project_store.forget_session("s1", agent_id="research")
    assert on_disk()["sessions"] == {}


@pytest.mark.parametrize("sweep", ["forget_agent", "delete_project"])
def test_sweeps_survive_bad_sessions(store, sweep):
    project_store, write, on_disk, project = store
    write(_shape(recents=[{"path": project}]))

    if sweep == "forget_agent":
        project_store.forget_agent("research")
    else:
        project_store.delete_project(project, agent_id="research")
        assert on_disk()["sessions"] == {} and on_disk()["recents"] == []
    assert project_store.get_project_map("research") == {}


def test_well_formed_file_is_untouched(store):
    project_store, write, on_disk, project = store
    write(_shape({"research::s1": {"path": project, "ts": 1.0}},
                 recents=[{"path": project, "name": "proj", "ts": 2.0}],
                 meta={project: {"display_name": "My project"}}, order=[project]))
    before = on_disk()

    assert project_store.get_project_map("research") == {"s1": project}
    assert project_store.display_name_for(project) == "My project"
    assert project_store.get_order() == [project]
    assert on_disk() == before
