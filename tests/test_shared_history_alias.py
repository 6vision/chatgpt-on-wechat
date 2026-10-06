"""A transcript handed to a remote teammate names this Agent one way only.

``CloudClient`` reports the default Agent to remote callers under the reserved
alias, because that is how they address it — ``AgentRegistry.get_addressed``
turns a bare ``"default"`` back into whichever Agent really holds that id. The
sender that does this covers the chunks that name a speaker:

    _SPEAKER_CHUNKS = ("speaker", "peer_start", "peer_end")

The shared transcript does not travel that way. ``_run_on_peer`` puts it on the
``InvokeRequest`` itself, so it never passes through ``send_chunk_fn`` and keeps
the real id:

    entry = {"role": ..., "text": ..., "agent_id": message.get("agent_id") or owner.id}

The far side then reads a conversation in which the same Agent appears under both
names, and attributes part of its own past to somebody who is not in its roster.

These tests drive the real ``_shared_history`` over a stubbed store and read the
author off what it produces.
"""

import pytest

from agent.registry import DEFAULT_AGENT_ALIAS


class _Profile:
    def __init__(self, agent_id, workspace="/tmp/alias-hist"):
        self.id = agent_id
        self.name = agent_id
        self.workspace = workspace


@pytest.fixture
def service():
    """A ChatService wired to a roster whose default has a real id."""
    from agent.chat import service as service_module
    from agent.registry import AgentProfile, AgentRegistry

    registry = AgentRegistry(
        [
            AgentProfile("main-agent", "Main", "/tmp/hist-w1"),
            AgentProfile("helper", "Helper", "/tmp/hist-w2"),
        ],
        "main-agent",
    )

    class FakeBridge:
        agent_registry = registry

    svc = service_module.ChatService.__new__(service_module.ChatService)
    svc.agent_bridge = FakeBridge()
    return svc, registry


def _turn(agent_id, text):
    """One stored turn: a user query and the reply it produced.

    The store filter keeps user/assistant *pairs*, so a lone assistant message
    is dropped before _shared_history ever sees it.
    """
    return [
        {"role": "user", "content": [{"type": "text", "text": "q"}]},
        {
            "role": "assistant",
            "agent_id": agent_id,
            "content": [{"type": "text", "text": text}],
        },
    ]


def _turns(*pairs):
    out = []
    for agent_id, text in pairs:
        out.extend(_turn(agent_id, text))
    return out


def _authors(history):
    """The agent_id of each assistant turn; user turns carry none."""
    return [e["agent_id"] for e in history if e["role"] == "assistant"]


def _history(svc, owner_id, saved, monkeypatch, persistence=True):
    """Drive the real _shared_history over a stubbed conversation store."""
    import agent.memory as memory_module
    import config as config_module

    class FakeStore:
        @staticmethod
        def load_messages(_sid, max_turns=0, with_authors=False):
            return saved

    monkeypatch.setattr(
        memory_module, "get_conversation_store", lambda *_a, **_k: FakeStore()
    )
    # Assigned rather than monkeypatched: _shared_history does `from config
    # import conf` inside the function, and the module attribute is what it
    # picks up.
    original = config_module.conf
    config_module.conf = lambda: {
        "conversation_persistence": persistence,
        "agent_max_context_turns": 20,
    }
    try:
        return svc._shared_history("s1", _Profile(owner_id))
    finally:
        config_module.conf = original


def test_the_default_agent_is_named_by_its_alias(service, monkeypatch):
    svc, _registry = service
    history = _history(
        svc, "main-agent", _turns(("main-agent", "on my machine")), monkeypatch
    )

    assert _authors(history) == ["default"]


def test_anybody_else_keeps_their_id(service, monkeypatch):
    svc, _registry = service
    history = _history(svc, "main-agent", _turns(("helper", "from the teammate")), monkeypatch)

    assert _authors(history) == ["helper"]


def test_a_turn_with_no_author_falls_back_to_the_owner(service, monkeypatch):
    """The owner speaks the turns it stored without an author label."""
    svc, _registry = service
    history = _history(
        svc,
        "main-agent",
        _turns(("main-agent", "hi")),
        monkeypatch,
    )

    assert _authors(history) == ["default"]


def test_both_spellings_arrive_as_the_alias(service, monkeypatch):
    """A transcript that used both names must not keep both."""
    svc, _registry = service
    history = _history(
        svc,
        "main-agent",
        _turns(("main-agent", "earlier"), ("helper", "theirs")),
        monkeypatch,
    )

    assert _authors(history) == ["default", "helper"]


def test_an_unreadable_roster_keeps_the_stored_author(service, monkeypatch):
    """A lookup that blows up must not lose the speaker."""
    svc, _registry = service

    class Broken:
        @property
        def default_agent_id(self):
            raise RuntimeError("registry is loading")

    monkeypatch.setattr(svc.agent_bridge, "agent_registry", Broken())
    history = _history(
        svc, "main-agent", _turns(("main-agent", "still here")), monkeypatch
    )

    assert _authors(history) == ["main-agent"]


def test_a_single_agent_install_is_unchanged(monkeypatch):
    """When the real id already is the alias there is nothing to rewrite."""
    from agent.chat import service as service_module
    from agent.registry import AgentProfile, AgentRegistry

    registry = AgentRegistry(
        [AgentProfile("default", "Solo", "/tmp/hist-solo")], "default"
    )

    class FakeBridge:
        agent_registry = registry

    svc = service_module.ChatService.__new__(service_module.ChatService)
    svc.agent_bridge = FakeBridge()
    history = _history(svc, "default", _turns(("default", "solo turn")), monkeypatch)

    assert _authors(history) == ["default"]


def test_user_turns_carry_no_author(service, monkeypatch):
    svc, _registry = service
    history = _history(
        svc,
        "main-agent",
        [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        monkeypatch,
    )

    assert ["agent_id" in e for e in history] == [False]


def test_persistence_off_yields_no_history(service, monkeypatch):
    svc, _registry = service
    history = _history(
        svc, "main-agent", _turns(("main-agent", "x")), monkeypatch, persistence=False
    )

    assert history == []


def test_the_history_exit_agrees_with_the_reserved_alias(service):
    """The history exit applies the one rule the chunk exit applies.

    ``CloudClient._alias_agent_id`` is a staticmethod over the *global*
    registry, so the cross-module comparison below needs that stack. This one
    pins the rule itself — the default Agent, and only the default Agent, comes
    out as the reserved alias — which is what the history exit has to match.
    """
    svc, registry = service

    assert svc._outside_agent_id(registry.default_agent_id) == DEFAULT_AGENT_ALIAS
    assert svc._outside_agent_id("helper") == "helper"
    assert svc._outside_agent_id("") == ""
    assert svc._outside_agent_id(None) is None


def test_the_history_exit_matches_the_speaker_chunk_exit(service, monkeypatch):
    """The two exits that name this Agent must not disagree.

    ``CloudClient._alias_agent_id`` is a staticmethod that reads the *global*
    registry, so the global has to be the roster under test — otherwise this
    compares the history exit against whatever Agent the machine running it
    happens to default to.
    """
    cloud_client = pytest.importorskip(
        "common.cloud_client", reason="cloud_client needs the optional linkai stack"
    )

    import agent.registry as registry_module

    svc, registry = service
    monkeypatch.setattr(registry_module, "get_agent_registry", lambda: registry)

    for agent_id in (registry.default_agent_id, "helper", ""):
        assert svc._outside_agent_id(agent_id) == cloud_client.CloudClient._alias_agent_id(
            agent_id
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
