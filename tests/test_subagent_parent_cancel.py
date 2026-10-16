"""A user Stop must reach running sub agents; timeouts stay per task."""

import json
import threading
from types import SimpleNamespace

import pytest

from agent.subagent import SubagentSettings, SubagentTask, runner
from agent.subagent.templates import GENERAL_PURPOSE
from agent.tools.subagent import SubagentTool

TEMPLATES = {GENERAL_PURPOSE.name: GENERAL_PURPOSE}


@pytest.fixture
def children(monkeypatch):
    """Stub children: goals starting with "slow" block until cancelled or released."""
    state = SimpleNamespace(started=[], events={}, entered=threading.Event(),
                            release=threading.Event())

    class Child:
        def run_stream(self, goal, clear_history, cancel_event, on_event, steer_inbox=None):
            state.started.append(goal)
            state.events[goal] = cancel_event
            if not goal.startswith("slow"):
                return f"{goal} done"
            state.entered.set()
            while not state.release.wait(0.01):
                if cancel_event.is_set():
                    return "stopped"
            return "released"

    monkeypatch.setattr(runner, "_build_child", lambda *args: Child())
    monkeypatch.setattr(runner, "_open_run", lambda *args: None)
    yield state
    state.release.set()


def _run_in_thread(*goals, cancel_event, **settings):
    results = []
    thread = threading.Thread(target=lambda: results.extend(runner.run_tasks(
        object(), [SubagentTask(g) for g in goals], TEMPLATES,
        SubagentSettings(**settings), cancel_event=cancel_event)))
    thread.start()
    return thread, results


def test_stop_reaches_running_child_and_cancels_queued_ones(children):
    stop = threading.Event()
    thread, results = _run_in_thread("slow", "queued", cancel_event=stop,
                                     max_concurrent=1, timeout_seconds=5)
    assert children.entered.wait(2)
    stop.set()
    thread.join(2)
    assert not thread.is_alive()
    assert children.events["slow"].is_set()
    assert children.started == ["slow"]
    assert [r["status"] for r in results] == ["cancelled", "cancelled"]


def test_stop_keeps_an_already_completed_sibling(children):
    stop = threading.Event()
    thread, results = _run_in_thread("slow", "sibling", cancel_event=stop, timeout_seconds=5)
    assert children.entered.wait(2)
    while "sibling" not in children.started:
        threading.Event().wait(0.01)
    threading.Event().wait(0.2)
    stop.set()
    thread.join(2)
    assert [r["status"] for r in results] == ["cancelled", "completed"]
    assert results[1]["summary"] == "sibling done"


def test_timeout_cancels_only_the_slow_child(children):
    stop = threading.Event()
    results = runner.run_tasks(object(), [SubagentTask("slow"), SubagentTask("sibling")],
                               TEMPLATES, SubagentSettings(timeout_seconds=0.2),
                               cancel_event=stop)
    assert [r["status"] for r in results] == ["timeout", "completed"]
    assert children.events["slow"].is_set()
    assert not children.events["sibling"].is_set()
    assert not stop.is_set()


def test_tool_passes_its_cancel_event_and_skips_children_once_stopped(children, monkeypatch, tmp_path):
    (tmp_path / "subagents").mkdir()
    monkeypatch.setattr(SubagentSettings, "from_config", classmethod(lambda cls: SubagentSettings()))
    tool = SubagentTool({"cwd": str(tmp_path)})
    tool.context = SimpleNamespace(workspace_dir=str(tmp_path))
    tool.cancel_event = threading.Event()
    tool.cancel_event.set()

    result = tool.execute({"goal": "investigate"})

    assert json.loads(result.result)["results"][0]["status"] == "cancelled"
    assert children.started == []
