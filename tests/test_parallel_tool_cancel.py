"""Giving up on a parallel tool prefetch that a cancel or a budget ended.

The parallel-safe calls of one turn all start at once, and the executor used to
collect them with a bare `future.result()` per call. That blocks until the
slowest tool finishes, and the loop's cancel checkpoint sits after this method
rather than inside it -- so a cancel pressed while the prefetch was still
waiting could not reach the workers. Every one of them ran to completion and the
turn stayed open for as long as the slowest one took.

The same fan-out in `agent/subagent/runner.py` already bounds its wait and
pushes the cancel into each worker. These tests pin the equivalent behaviour
here: the wait ends on cancel or on budget, and the calls that were still
running are reported rather than silently dropped.
"""

import threading
import time

import pytest

from agent.protocol import agent_stream
from agent.protocol.agent_stream import AgentStreamExecutor
from agent.tools.base_tool import BaseTool, ToolResult


class _GatedTool(BaseTool):
    """Returns at once for tags in `quick`, and otherwise blocks until released.

    Waiting on an event rather than sleeping keeps the abandoned worker threads
    from outliving the test that walked away from them, and keying on the tag
    lets one turn mix a call that finishes with one that never does.
    """

    name = "gated"
    parallel_safe = True
    params = {"type": "object", "properties": {"tag": {"type": "string"}}}

    def __init__(self, release, quick=()):
        self.release = release
        self.quick = set(quick)
        self.seen = []

    def execute(self, params):
        tag = params["tag"]
        self.seen.append(tag)
        if tag not in self.quick:
            self.release.wait(timeout=30)
        return ToolResult.success(tag)


class _ExplodingTool(_GatedTool):
    def execute(self, params):
        tag = params["tag"]
        self.seen.append(tag)
        if tag == "t0":
            raise RuntimeError("boom")
        self.release.wait(timeout=30)
        return ToolResult.success(tag)


def _executor(tool, cancel_event=None):
    executor = object.__new__(AgentStreamExecutor)
    executor.tools = {tool.name: tool}
    executor.model = None
    executor.agent = None
    executor.cancel_event = cancel_event
    executor._record_tool_result = lambda *a, **kw: None
    executor._check_consecutive_failures = lambda *a, **kw: (False, None, False)
    executor._emit_event = lambda *a, **kw: None
    return executor


def _calls(tags):
    return [
        {"id": f"call_{i}", "name": "gated", "arguments": {"tag": tag}}
        for i, tag in enumerate(tags)
    ]


@pytest.fixture
def release():
    """Released on teardown so abandoned worker threads wind down promptly."""
    event = threading.Event()
    yield event
    event.set()


def _cancel_after(event, seconds):
    """Press `event` from another thread, the way the session's UI thread would."""
    timer = threading.Timer(seconds, event.set)
    timer.daemon = True
    timer.start()
    return timer


def test_a_cancel_stops_the_wait_instead_of_running_every_worker_out(release):
    """The heart of it: the cancel arrives mid-prefetch and the call returns
    without waiting for the tools, which are still running at that point."""
    cancel = threading.Event()
    executor = _executor(_GatedTool(release), cancel)
    _cancel_after(cancel, 0.2)

    started = time.time()
    results = executor._run_parallel_calls(_calls(["t0", "t1"]))
    elapsed = time.time() - started

    # Both workers sit in `release.wait(timeout=30)`; a bare future.result()
    # would have waited them out.
    assert elapsed < 5, f"waited {elapsed:.1f}s for tools the cancel abandoned"
    assert sorted(results) == ["call_0", "call_1"]


def test_calls_that_finished_before_the_cancel_keep_their_result(release):
    """Abandoning the slow ones must not cost the caller the quick one: its
    result is already in hand and the loop should still see it."""
    cancel = threading.Event()
    executor = _executor(_GatedTool(release, quick={"quick"}), cancel)
    _cancel_after(cancel, 0.3)

    results = executor._run_parallel_calls(_calls(["quick", "stuck"]))

    assert results["call_0"]["status"] == "success"
    assert results["call_0"]["result"] == "quick"
    assert results["call_1"]["status"] == "error"


def test_an_abandoned_call_is_reported_as_an_error_the_caller_can_pass_on(release):
    """The loop looks each id up in the returned map, so a call that was still
    running needs an entry of its own rather than a hole."""
    cancel = threading.Event()
    executor = _executor(_GatedTool(release), cancel)
    cancel.set()

    results = executor._run_parallel_calls(_calls(["t0", "t1"]))

    assert sorted(results) == ["call_0", "call_1"]
    for result in results.values():
        assert result["status"] == "error"
        assert "discarded" in result["result"]


def test_an_unset_cancel_event_leaves_the_calls_to_finish(release):
    """`cancel_event` is None on executors built outside a running session. A
    wait that read that as "cancelled" would empty every result."""
    executor = _executor(
        _GatedTool(release, quick={"t0", "t1"}), cancel_event=None)

    results = executor._run_parallel_calls(_calls(["t0", "t1"]))

    assert [r["status"] for r in results.values()] == ["success", "success"]
    assert sorted(r["result"] for r in results.values()) == ["t0", "t1"]


def test_a_cancel_event_that_is_never_pressed_does_not_cut_the_wait_short(release):
    """The counterpart: an Event nobody sets must leave the prefetch alone, so
    a blocked tool is still waited for rather than written off."""
    executor = _executor(_GatedTool(release), cancel_event=threading.Event())

    threading.Timer(0.05, release.set).start()
    results = executor._run_parallel_calls(_calls(["t0", "t1"]))

    assert sorted(r["result"] for r in results.values()) == ["t0", "t1"]


def test_a_tool_that_never_returns_is_cut_off_by_the_budget(release, monkeypatch):
    """No cancel, no exit: a tool that hangs must not hold the turn open for
    good, so the budget is the backstop."""
    monkeypatch.setattr(agent_stream, "PARALLEL_PREFETCH_TIMEOUT_SECONDS", 0.6)
    monkeypatch.setattr(agent_stream, "PARALLEL_POLL_SECONDS", 0.1)
    executor = _executor(_GatedTool(release))

    started = time.time()
    results = executor._run_parallel_calls(_calls(["t0", "t1"]))
    elapsed = time.time() - started

    assert elapsed < 5, f"budget did not bound the wait ({elapsed:.1f}s)"
    assert sorted(results) == ["call_0", "call_1"]
    assert all(r["status"] == "error" for r in results.values())


def test_the_budget_collects_what_finished_and_only_abandons_the_rest(
        release, monkeypatch):
    """Same cut-off, but one call is quick: it must not be thrown away with
    the slow one just because they shared a budget."""
    monkeypatch.setattr(agent_stream, "PARALLEL_PREFETCH_TIMEOUT_SECONDS", 0.8)
    monkeypatch.setattr(agent_stream, "PARALLEL_POLL_SECONDS", 0.1)
    executor = _executor(_GatedTool(release, quick={"quick"}))

    results = executor._run_parallel_calls(_calls(["quick", "stuck"]))

    assert results["call_0"]["status"] == "success"
    assert results["call_0"]["result"] == "quick"
    assert results["call_1"]["status"] == "error"


def test_one_failing_call_still_leaves_its_siblings_reported(release):
    """A tool that raises is one call among several; its error belongs to its
    own id and the sibling still gets whatever it produced."""
    executor = _executor(_ExplodingTool(release))

    threading.Timer(0.05, release.set).start()
    results = executor._run_parallel_calls(_calls(["t0", "t1"]))

    assert results["call_0"]["status"] == "error"
    assert "boom" in results["call_0"]["result"]
    assert results["call_1"]["status"] == "success"
    assert results["call_1"]["result"] == "t1"


def test_the_caller_regains_control_while_a_worker_is_still_running(release):
    """`pool.shutdown(wait=False)` is what keeps abandoned tools from holding
    the turn, so the executor has to come back while a worker is provably still
    inside the tool -- not after it has wound down."""
    finished = []

    class _WatchingTool(_GatedTool):
        def execute(self, params):
            self.seen.append(params["tag"])
            self.release.wait(timeout=30)
            finished.append(params["tag"])
            return ToolResult.success(params["tag"])

    cancel = threading.Event()
    executor = _executor(_WatchingTool(release), cancel)
    _cancel_after(cancel, 0.2)

    started = time.time()
    results = executor._run_parallel_calls(_calls(["t0", "t1"]))
    elapsed = time.time() - started

    assert sorted(executor.tools["gated"].seen) == ["t0", "t1"], \
        "the calls never started"
    assert finished == [], "the wait only returned after the workers finished"
    assert elapsed < 5, f"waited {elapsed:.1f}s for tools the cancel abandoned"
    assert all(r["status"] == "error" for r in results.values())
