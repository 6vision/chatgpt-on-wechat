"""A run resets the fallback for itself, never for the run it is nested in.

The fallback is an ordered chain, and it is sticky for a whole run: once the
primary model has failed a turn for good, the remaining steps stay on whichever
link answered instead of re-probing a provider we already know is down. It is
cleared once, at the top of a run.

That breaks when the parent delegates. A sub agent is built with
``model=parent.model`` — the *same* ``AgentLLMModel`` object, not a copy — and
its ``run_stream`` runs that same reset at its top. The child therefore clears
the fallback the parent is currently relying on: when the child returns, the
parent goes back to the primary model that just failed and burns the full retry
budget again on every remaining step. The child loses the backup too, since it
is running inside the same outage and starts on the dead primary itself — and
with a chain it would also rewind the parent to link 1, throwing away the
progress of every link already proven to be down.

The opposite failure is just as bad: a top-level turn that skips the reset
stays on the backup forever, ignoring the model the conversation is pinned to.
An ambient run id cannot tell the two apart — the bridge opens a run, and sets
its id, before every top-level turn — so these drive the real ``run_stream``
the way the bridge and the sub agent runner enter it.
"""

import contextvars
import threading

import pytest

from bridge.agent_bridge import AgentLLMModel

FALLBACK = {
    "enabled": True,
    "chain": [
        {"provider": "openai", "model": "backup-model"},
        {"provider": "qianfan", "model": "backup-model-2"},
    ],
}


def _model(monkeypatch, chat_fallback, **extra_conf):
    """An AgentLLMModel with a stubbed config (no bridge, no real bot)."""
    conf = {"model": "primary-model", "chat_fallback": chat_fallback}
    conf.update(extra_conf)
    monkeypatch.setattr("bridge.agent_bridge.conf", lambda: conf, raising=False)
    return AgentLLMModel.__new__(AgentLLMModel)


@pytest.fixture
def executor_cls():
    from agent.protocol.agent_stream import AgentStreamExecutor

    return AgentStreamExecutor


def _run(executor_cls, model, during=None):
    """Drive the real run_stream for one answer; return the model each call saw.

    ``during`` runs inside the LLM call, i.e. while the run is live — where a
    parent fails over or spawns a sub agent.
    """
    seen = []
    executor = executor_cls(agent=None, model=model, system_prompt="", tools=[])

    def _call_llm_stream(**_kwargs):
        seen.append(model.model)
        if during is not None:
            during()
        return "ok", [], "end_turn"

    executor._call_llm_stream = _call_llm_stream
    executor.run_stream("hi")
    return seen


def _bridge_turn(executor_cls, model, during=None):
    """A top-level turn the way AgentBridge enters it: run id already set."""
    from common.runtime_identity import identity_scope

    with identity_scope(run_id="bridge-run"):
        return _run(executor_cls, model, during)


def _spawn_child(executor_cls, model):
    """Run a sub agent the way the runner does: copied context, worker thread,
    its own run id. Returns the model each of its calls saw."""
    from common.runtime_identity import identity_scope

    out = {}

    def _child():
        with identity_scope(run_id="child-run"):
            out["seen"] = _run(executor_cls, model)

    ctx = contextvars.copy_context()
    worker = threading.Thread(target=ctx.run, args=(_child,))
    worker.start()
    worker.join()
    return out["seen"]


class TestTopLevelTurnStartsOnThePrimary:

    def test_a_bridge_turn_resets_a_fallback_left_by_the_previous_turn(
        self, monkeypatch, executor_cls
    ):
        """The regression: a pinned conversation kept answering on the backup."""
        model = _model(monkeypatch, FALLBACK)
        model.set_session_override("claudeAPI", "claude-opus-5-5")
        assert model.use_fallback() is True
        assert model.use_fallback() is True
        assert model.model == "backup-model-2"

        assert _bridge_turn(executor_cls, model) == ["claude-opus-5-5"]

    def test_the_turn_log_names_the_model_it_starts_on(self, monkeypatch, executor_cls):
        """Not the backup the previous turn ended on."""
        import agent.protocol.agent_stream as agent_stream

        model = _model(monkeypatch, FALLBACK)
        model.set_session_override("claudeAPI", "claude-opus-5-5")
        model.use_fallback()
        lines = []
        monkeypatch.setattr(
            agent_stream.logger, "info", lambda msg, *a, **k: lines.append(str(msg))
        )

        _bridge_turn(executor_cls, model)

        turn_line = next(line for line in lines if line.startswith("🤖 "))
        assert turn_line.startswith("🤖 claude-opus-5-5 ")

    def test_a_turn_without_an_ambient_run_id_resets_too(self, monkeypatch, executor_cls):
        model = _model(monkeypatch, FALLBACK)
        model.use_fallback()

        assert _run(executor_cls, model) == ["primary-model"]

    def test_the_next_turn_walks_the_chain_from_the_front(self, monkeypatch, executor_cls):
        model = _model(monkeypatch, FALLBACK)
        model.use_fallback()
        model.use_fallback()
        _bridge_turn(executor_cls, model)

        assert model.fallback_available() is True
        assert model.use_fallback() is True
        assert model.model == "backup-model"


class TestSubAgentDoesNotClearParentFallback:

    def _parent_spawning_after(self, executor_cls, model, links):
        """A parent turn that fails over ``links`` times, then spawns a child."""
        state = {}

        def _during():
            for _ in range(links):
                assert model.use_fallback() is True
            state["parent_before"] = model.model
            state["child"] = _spawn_child(executor_cls, model)
            state["parent_after"] = model.model

        _bridge_turn(executor_cls, model, during=_during)
        return state

    def test_a_sub_agent_keeps_the_parents_engaged_fallback(
        self, monkeypatch, executor_cls
    ):
        model = _model(monkeypatch, FALLBACK)

        state = self._parent_spawning_after(executor_cls, model, links=1)

        assert state["child"] == ["backup-model"], (
            "the sub agent started on the primary the parent just proved down"
        )
        assert state["parent_after"] == "backup-model", (
            "the sub agent cleared the fallback the parent is still relying on; "
            "the parent will re-probe the failed primary on its next step"
        )

    def test_a_parent_that_walked_two_links_keeps_its_position(
        self, monkeypatch, executor_cls
    ):
        """The child must not rewind the parent to link 1 after it already
        proved link 1 was down."""
        model = _model(monkeypatch, FALLBACK)

        state = self._parent_spawning_after(executor_cls, model, links=2)

        assert state["parent_after"] == "backup-model-2"
        assert model.fallback_available() is True
        assert model.use_fallback() is True
        assert model.model == "backup-model"  # wrapped around: pass 2, link 1

    def test_a_nested_run_on_its_own_model_still_resets_it(
        self, monkeypatch, executor_cls
    ):
        """Only a shared model object is protected: a teammate answering on its
        own model starts that model fresh, like any other turn."""
        parent_model = _model(monkeypatch, FALLBACK)
        other = AgentLLMModel.__new__(AgentLLMModel)
        other.use_fallback()
        state = {}

        def _during():
            state["other"] = _spawn_child(executor_cls, other)

        _bridge_turn(executor_cls, parent_model, during=_during)

        assert state["other"] == ["primary-model"]

    def test_the_active_run_marker_is_released_after_the_run(
        self, monkeypatch, executor_cls
    ):
        from agent.protocol.agent_stream import _ACTIVE_RUN_MODELS

        model = _model(monkeypatch, FALLBACK)
        _bridge_turn(executor_cls, model)

        assert _ACTIVE_RUN_MODELS.get() == frozenset()
