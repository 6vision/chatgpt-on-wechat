"""Pin that serve_invoke folds the reserved ``default`` alias onto the default Agent's real id."""

import pytest


def _registry(default_id, profiles=(("main-agent", "Main"), ("helper", "Helper"))):
    from agent.registry import AgentProfile, AgentRegistry

    return AgentRegistry(
        [AgentProfile(pid, name, f"/tmp/alias-{pid}") for pid, name in profiles], default_id
    )


def _serve(trace, addressed, registry, monkeypatch, **overrides):
    from agent.multiagent.inbound import serve_invoke
    from bridge.reply import Reply, ReplyType
    import config as config_module

    seen = {}

    class Bridge:
        agent_registry = registry

        def agent_reply(self, query, context=None, on_event=None):
            seen["context"] = context
            return Reply(ReplyType.TEXT, "ok")

    payload = dict(
        request_id="req-1", mode="delegate", source_agent_id="helper", source_name="Helper",
        target_agent_id=addressed, task="read the config", root_session_id="root-1", trace=trace,
        **overrides,
    )
    chunks = []
    monkeypatch.setattr(config_module, "conf", lambda: {"agent_delegation": {}})
    serve_invoke(payload, Bridge(), chunks.append)
    return seen.get("context"), (chunks[-1] if chunks else {})


@pytest.mark.parametrize(
    "default_id, trace",
    [
        ("main-agent", ["helper", "main-agent", "default"]),
        ("main-agent", ["main-agent", "helper", "main-agent"]),
        ("main-agent", ["default", "helper"]),
        # With helper as the default, "default" means helper and must not fold onto main-agent.
        ("helper", ["main-agent", "helper"]),
    ],
)
def test_cycles_are_rejected_under_either_name(monkeypatch, default_id, trace):
    _context, last = _serve(trace, "main-agent", _registry(default_id), monkeypatch)

    assert last.get("status") == "failed"
    error = last.get("error") or ""
    assert "cycle rejected" in error
    if default_id == "main-agent":
        assert "default" not in error


@pytest.mark.parametrize("trace, addressed", [(["helper"], "main-agent"), (["helper", "default"], "default")])
def test_fresh_chain_runs_with_alias_folded(monkeypatch, trace, addressed):
    context, last = _serve(trace, addressed, _registry("main-agent"), monkeypatch, members=["default", "helper"])

    assert last.get("status") == "done"
    assert context["delegation_trace"] == ["helper", "main-agent"]
    assert "default" not in context["delegation_members"]


def test_single_agent_install_is_unaffected(monkeypatch):
    roster = _registry("default", profiles=(("default", "Solo"),))
    context, last = _serve(["helper"], "default", roster, monkeypatch)

    assert last.get("status") == "done"
    assert context["delegation_trace"] == ["helper", "default"]
