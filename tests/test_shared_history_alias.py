"""Pin that the shared history names the default Agent by the reserved alias for remote callers."""

import pytest

from agent.registry import DEFAULT_AGENT_ALIAS


class _Profile:
    def __init__(self, agent_id):
        self.id = agent_id
        self.name = agent_id
        self.workspace = "/tmp/alias-hist"


def _service(profiles, default_id):
    from agent.chat import service as service_module
    from agent.registry import AgentProfile, AgentRegistry

    registry = AgentRegistry([AgentProfile(*p) for p in profiles], default_id)

    class FakeBridge:
        agent_registry = registry

    svc = service_module.ChatService.__new__(service_module.ChatService)
    svc.agent_bridge = FakeBridge()
    return svc


@pytest.fixture
def svc():
    return _service(
        [("main-agent", "Main", "/tmp/hist-w1"), ("helper", "Helper", "/tmp/hist-w2")],
        "main-agent",
    )


def _turns(*authors):
    out = []
    for agent_id in authors:
        reply = {"role": "assistant", "content": [{"type": "text", "text": "a"}]}
        if agent_id is not None:
            reply["agent_id"] = agent_id
        out += [{"role": "user", "content": [{"type": "text", "text": "q"}]}, reply]
    return out


def _history(svc, owner_id, saved, monkeypatch, persistence=True):
    import agent.memory as memory_module
    import config as config_module

    class FakeStore:
        @staticmethod
        def load_messages(_sid, max_turns=0, with_authors=False):
            return saved

    monkeypatch.setattr(memory_module, "get_conversation_store", lambda *_a, **_k: FakeStore())
    monkeypatch.setattr(
        config_module,
        "conf",
        lambda: {"conversation_persistence": persistence, "agent_max_context_turns": 20},
    )
    return svc._shared_history("s1", _Profile(owner_id))


def _authors(history):
    return [e["agent_id"] for e in history if e["role"] == "assistant"]


@pytest.mark.parametrize(
    "authors, expected",
    [
        (["main-agent"], ["default"]),
        (["helper"], ["helper"]),
        ([None], ["default"]),
        (["main-agent", "helper"], ["default", "helper"]),
    ],
)
def test_default_agent_is_named_by_alias(svc, monkeypatch, authors, expected):
    assert _authors(_history(svc, "main-agent", _turns(*authors), monkeypatch)) == expected


def test_unreadable_roster_keeps_stored_author(svc, monkeypatch):
    class Broken:
        @property
        def default_agent_id(self):
            raise RuntimeError("registry is loading")

    monkeypatch.setattr(svc.agent_bridge, "agent_registry", Broken())
    assert _authors(_history(svc, "main-agent", _turns("main-agent"), monkeypatch)) == ["main-agent"]


def test_single_agent_install_is_unchanged(monkeypatch):
    solo = _service([("default", "Solo", "/tmp/hist-solo")], "default")
    assert _authors(_history(solo, "default", _turns("default"), monkeypatch)) == ["default"]


def test_user_turns_carry_no_author(svc, monkeypatch):
    saved = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    assert ["agent_id" in e for e in _history(svc, "main-agent", saved, monkeypatch)] == [False]


def test_persistence_off_yields_no_history(svc, monkeypatch):
    assert _history(svc, "main-agent", _turns("main-agent"), monkeypatch, persistence=False) == []


def test_outside_agent_id_maps_only_the_default(svc):
    assert svc._outside_agent_id("main-agent") == DEFAULT_AGENT_ALIAS
    assert svc._outside_agent_id("helper") == "helper"
    assert svc._outside_agent_id("") == ""
    assert svc._outside_agent_id(None) is None
