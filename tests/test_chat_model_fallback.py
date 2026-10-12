"""Fallback chat chain: when it engages, and when it must stay out of the way.

The fallback is opt-in and only takes over once a turn has failed for good, so
these tests pin down both directions — that a dead provider hands over to the
first backup, that a backup which also fails hands over to the one after it,
and that a healthy primary is never disturbed. The failure modes worth guarding
are the quiet ones: a half-configured entry silently answering for a working
model, or a chain that loops back onto a model already proven to be down.
"""

import pytest

from bridge.agent_bridge import AgentLLMModel


def _model(monkeypatch, chat_fallback, **extra_conf):
    """An AgentLLMModel with a stubbed config (no bridge, no real bot)."""
    conf = {"model": "primary-model", "chat_fallback": chat_fallback}
    conf.update(extra_conf)
    monkeypatch.setattr("bridge.agent_bridge.conf", lambda: conf, raising=False)
    return AgentLLMModel.__new__(AgentLLMModel)


def _chain(*links, enabled=True):
    """A chain config from (provider, model) pairs."""
    return {
        "enabled": enabled,
        "chain": [{"provider": p, "model": m} for p, m in links],
    }


FALLBACK = _chain(("openai", "backup-model"))


class TestFallbackConfig:
    """A malformed or disabled entry must never be usable."""

    def test_a_disabled_entry_is_not_available(self, monkeypatch):
        model = _model(monkeypatch, _chain(("openai", "backup-model"), enabled=False))
        assert model.fallback_available() is False

    def test_a_missing_entry_is_not_available(self, monkeypatch):
        model = _model(monkeypatch, None)
        assert model.fallback_available() is False

    def test_a_non_dict_entry_is_not_available(self, monkeypatch):
        model = _model(monkeypatch, "openai/backup-model")
        assert model.fallback_available() is False

    def test_an_empty_chain_is_not_available(self, monkeypatch):
        """Enabled with nothing in it: there is no backup to fall back to."""
        model = _model(monkeypatch, {"enabled": True, "chain": []})
        assert model.fallback_available() is False

    @pytest.mark.parametrize(
        "field",
        ["provider", "model"],
    )
    def test_a_half_configured_link_is_dropped(self, monkeypatch, field):
        """Half a link routes nowhere, and must not make the chain look usable."""
        link = {"provider": "openai", "model": "backup-model"}
        link[field] = ""
        model = _model(monkeypatch, {"enabled": True, "chain": [link]})
        assert model.fallback_config()["chain"] == []
        assert model.fallback_available() is False

    def test_a_non_dict_link_is_ignored(self, monkeypatch):
        model = _model(monkeypatch, {"enabled": True, "chain": ["openai/backup", 42, None]})
        assert model.fallback_config()["chain"] == []

    def test_a_garbage_chain_does_not_raise(self, monkeypatch):
        model = _model(monkeypatch, {"enabled": True, "chain": "openai/backup"})
        assert model.fallback_available() is False

    def test_the_primary_model_is_stripped_from_the_chain(self, monkeypatch):
        """Listing the primary as its own backup would bounce the turn straight
        back onto the model that just failed."""
        model = _model(
            monkeypatch,
            _chain(("openai", "primary-model"), ("openai", "backup-model")),
        )
        assert model.fallback_config()["chain"] == [
            {"provider": "openai", "model": "backup-model"}
        ]

    def test_duplicate_links_are_collapsed(self, monkeypatch):
        """The same backup twice would spend a switch to re-probe a dead model."""
        model = _model(
            monkeypatch,
            _chain(("openai", "backup-model"), ("openai", "backup-model")),
        )
        assert model.fallback_config()["chain"] == [
            {"provider": "openai", "model": "backup-model"}
        ]

    def test_a_same_model_link_behind_another_provider_is_kept(self, monkeypatch):
        """The same model name behind another provider — a second account or
        endpoint of it — is a legitimate backup, not a duplicate of the primary.
        The dedup used to compare the model name alone whenever the primary
        carried no provider pin, silently dropping every such link."""
        model = _model(
            monkeypatch,
            _chain(("custom:agnes-2", "agnes-2.5-flash"), ("baishan", "glm-4.7")),
            model="agnes-2.5-flash",
            bot_type="custom:agnes-1",
        )
        assert model.fallback_config()["chain"] == [
            {"provider": "custom:agnes-2", "model": "agnes-2.5-flash"},
            {"provider": "baishan", "model": "glm-4.7"},
        ]

    def test_the_primarys_own_route_is_stripped_with_a_custom_provider(self, monkeypatch):
        """A link naming the primary's provider *and* model is still dropped:
        that one would bounce the turn straight back onto the failed route."""
        model = _model(
            monkeypatch,
            _chain(("custom:agnes-1", "agnes-2.5-flash"), ("baishan", "glm-4.7")),
            model="agnes-2.5-flash",
            bot_type="custom:agnes-1",
        )
        assert model.fallback_config()["chain"] == [
            {"provider": "baishan", "model": "glm-4.7"}
        ]

    def test_the_linkai_route_is_stripped(self, monkeypatch):
        """use_linkai routes the primary through LinkAI; a link naming that
        provider with the primary's model is the same route, so it drops."""
        model = _model(
            monkeypatch,
            _chain(("linkai", "primary-model"), ("openai", "backup-model")),
            use_linkai=True,
            linkai_api_key="sk-live",
        )
        assert model.fallback_config()["chain"] == [
            {"provider": "openai", "model": "backup-model"}
        ]

    def test_the_legacy_single_model_shape_is_honored(self, monkeypatch):
        """A pre-chain config keeps working: config.py normally upgrades it at
        load time, but a caller handing over the raw dict must not lose it."""
        model = _model(monkeypatch, {
            "enabled": True,
            "provider": "openai",
            "model": "backup-model",
            "max_switches": 1,
        })
        assert model.fallback_config()["chain"] == [
            {"provider": "openai", "model": "backup-model"}
        ]


class TestEngagingTheFallback:
    def test_the_answer_comes_from_the_first_link(self, monkeypatch):
        model = _model(monkeypatch, FALLBACK)
        assert model.model == "primary-model"

        assert model.use_fallback() is True
        assert model.model == "backup-model"

    def test_routing_follows_the_fallback_provider(self, monkeypatch):
        """The bot type has to change too, or the request would go back to the
        provider that just failed."""
        model = _model(monkeypatch, _chain(("qianfan", "backup-model")))
        model.use_fallback()
        assert model._resolve_bot_type("backup-model") == "qianfan"

    def test_openai_routes_through_the_compatible_bot(self, monkeypatch):
        """Same mapping the models console persists for the primary model."""
        model = _model(monkeypatch, FALLBACK)
        model.use_fallback()
        assert model._resolve_bot_type("backup-model") == "chatGPT"

    def test_it_outranks_a_session_override(self, monkeypatch):
        """A user's per-conversation pick shouldn't survive their own provider
        going down — the fallback exists precisely to leave it."""
        model = _model(monkeypatch, FALLBACK)
        model.set_session_override("deepseek", "pinned-model")
        model.use_fallback()
        assert model.model == "backup-model"

    def test_disabled_fallback_returns_false(self, monkeypatch):
        model = _model(monkeypatch, _chain(("openai", "backup-model"), enabled=False))
        assert model.use_fallback() is False
        assert model.model == "primary-model"


class TestWalkingTheChain:
    """A backup that fails must earn the next one, not end the turn."""

    def test_a_failed_link_advances_to_the_next(self, monkeypatch):
        model = _model(monkeypatch, _chain(
            ("openai", "backup-1"),
            ("qianfan", "backup-2"),
            ("zhipu", "backup-3"),
        ))
        assert model.use_fallback() is True
        assert model.model == "backup-1"
        assert model.use_fallback() is True
        assert model.model == "backup-2"
        assert model.use_fallback() is True
        assert model.model == "backup-3"

    def test_the_walk_wraps_around_after_the_last_link(self, monkeypatch):
        """Reaching the last link is not the end of the turn.

        The walk comes back to the first link: a whole pass takes real time,
        so a rate limit that blocked link 1 on the way through may well have
        cleared by the time the walk returns to it.
        """
        model = _model(monkeypatch, _chain(("openai", "backup-1"), ("qianfan", "backup-2")))
        assert model.use_fallback() is True
        assert model.model == "backup-1"
        assert model.use_fallback() is True
        assert model.model == "backup-2"
        # Wraps around to the front again rather than giving up.
        assert model.use_fallback() is True
        assert model.model == "backup-1"

    def test_the_walk_stops_after_two_passes(self, monkeypatch):
        """Two passes, then the turn reports failure.

        Unbounded would hang the turn on a chain whose providers are all
        genuinely down, and the user would sit through every extra pass.
        """
        model = _model(monkeypatch, _chain(("openai", "backup-1"), ("qianfan", "backup-2")))
        # 2 links x 2 passes = 4 advances, then the chain is spent.
        assert [model.use_fallback() for _ in range(4)] == [True] * 4
        assert model.fallback_available() is False
        assert model.use_fallback() is False

    def test_routing_follows_each_link_in_turn(self, monkeypatch):
        """Every link carries its own provider, so a chain can leave a whole
        vendor behind rather than one model."""
        model = _model(monkeypatch, _chain(("openai", "backup-1"), ("qianfan", "backup-2")))
        model.use_fallback()
        assert model._resolve_bot_type("backup-1") == "chatGPT"
        model.use_fallback()
        assert model._resolve_bot_type("backup-2") == "qianfan"

    def test_a_long_chain_is_not_capped(self, monkeypatch):
        """There is no separate switch limit to hit: five links, five tries
        per pass."""
        links = [(f"provider-{i}", f"backup-{i}") for i in range(5)]
        model = _model(monkeypatch, _chain(*links))
        assert [model.use_fallback() for _ in range(5)] == [True] * 5
        # A second pass is still available — five links is not a hard cap on
        # the number of switches, the pass budget is.
        assert model.fallback_available() is True
        assert [model.use_fallback() for _ in range(5)] == [True] * 5
        assert model.fallback_available() is False
        assert model.model == "backup-4"


class TestResettingBetweenTurns:
    def test_a_new_turn_starts_on_the_primary_again(self, monkeypatch):
        """Scoping the switch to one turn keeps a transient outage from
        quietly downgrading the rest of the conversation."""
        model = _model(monkeypatch, FALLBACK)
        model.use_fallback()
        model.reset_fallback()
        assert model.model == "primary-model"

    def test_reset_rewinds_the_whole_chain(self, monkeypatch):
        """A run that had walked three links starts the next one from link 1,
        not from wherever the previous turn gave up."""
        model = _model(monkeypatch, _chain(
            ("openai", "backup-1"), ("qianfan", "backup-2"), ("zhipu", "backup-3"),
        ))
        model.use_fallback()
        model.use_fallback()
        model.use_fallback()
        assert model.model == "backup-3"

        model.reset_fallback()
        assert model.model == "primary-model"
        assert model.use_fallback() is True
        assert model.model == "backup-1"

    def test_reset_on_a_healthy_model_is_a_no_op(self, monkeypatch):
        model = _model(monkeypatch, FALLBACK)
        model.reset_fallback()
        assert model.model == "primary-model"


class TestStreamRecovery:
    """The executor only asks to switch once retries are exhausted."""

    def test_a_plain_model_is_never_asked_to_switch(self):
        """Doubles and plain LLMModels have no use_fallback; the turn must
        still fail normally instead of erroring on a missing method."""
        from agent.protocol.agent_stream import AgentStreamExecutor

        executor = AgentStreamExecutor.__new__(AgentStreamExecutor)
        executor.model = object()
        assert executor._switch_to_fallback("boom") is False

    def test_a_failing_switch_does_not_break_the_turn(self):
        from agent.protocol.agent_stream import AgentStreamExecutor

        class Broken:
            def use_fallback(self):
                raise RuntimeError("config is unreadable")

        executor = AgentStreamExecutor.__new__(AgentStreamExecutor)
        executor.model = Broken()
        assert executor._switch_to_fallback("boom") is False

    def test_reset_is_a_no_op_without_support(self):
        from agent.protocol.agent_stream import AgentStreamExecutor

        executor = AgentStreamExecutor.__new__(AgentStreamExecutor)
        executor.model = object()
        executor._reset_model_fallback()  # must not raise

    def test_the_switch_delegates_to_the_model(self, monkeypatch):
        from agent.protocol.agent_stream import AgentStreamExecutor

        calls = []

        class Fake:
            def use_fallback(self):
                calls.append(True)
                return True

        executor = AgentStreamExecutor.__new__(AgentStreamExecutor)
        executor.model = Fake()
        assert executor._switch_to_fallback("provider is down") is True
        assert calls == [True]


class TestConsoleValidation:
    """The models console must not persist a chain that can't do its job."""

    def _handler(self):
        from channel.web.api.models import ModelsHandler

        return ModelsHandler.__new__(ModelsHandler)

    def _saved(self, monkeypatch, *args, **kwargs):
        written = {}
        monkeypatch.setattr(
            "channel.web.api.models.conf", lambda: {"model": "primary-model"}
        )
        handler = self._handler()
        monkeypatch.setattr(handler, "_read_file_config", lambda: {})
        monkeypatch.setattr(
            handler, "_write_file_config", lambda cfg: written.update(cfg)
        )
        result = handler._set_chat_fallback(*args, **kwargs)
        return result, written

    def test_enabling_without_a_model_is_rejected(self, monkeypatch):
        result, _ = self._saved(monkeypatch, "openai", "", True)
        assert "error" in result

    def test_enabling_without_a_provider_is_rejected(self, monkeypatch):
        result, _ = self._saved(monkeypatch, "", "backup-model", True)
        assert "error" in result

    def test_enabling_with_an_empty_chain_is_rejected(self, monkeypatch):
        result, _ = self._saved(monkeypatch, "", "", True, chain=[])
        assert "error" in result

    def test_disabling_a_broken_entry_is_always_allowed(self, monkeypatch):
        """Turning it off is the safe direction — never block the user."""
        result, written = self._saved(monkeypatch, "", "", False)
        assert '"status": "success"' in result
        assert written["chat_fallback"]["enabled"] is False

    def test_an_unknown_provider_is_rejected(self, monkeypatch):
        result, _ = self._saved(monkeypatch, "not-a-vendor", "m", True)
        assert "error" in result

    def test_an_unknown_provider_inside_the_chain_is_rejected(self, monkeypatch):
        result, _ = self._saved(
            monkeypatch, "", "", True,
            chain=[{"provider": "openai", "model": "ok"},
                   {"provider": "not-a-vendor", "model": "m"}],
        )
        assert "error" in result

    def test_the_chain_is_persisted_in_order(self, monkeypatch):
        """Order is the whole point: link 1 is tried before link 2."""
        result, written = self._saved(
            monkeypatch, "", "", True,
            chain=[{"provider": "openai", "model": "backup-1"},
                   {"provider": "qianfan", "model": "backup-2"}],
        )
        assert '"status": "success"' in result
        assert written["chat_fallback"]["chain"] == [
            {"provider": "openai", "model": "backup-1"},
            {"provider": "qianfan", "model": "backup-2"},
        ]

    def test_a_long_chain_is_persisted_whole(self, monkeypatch):
        """No cap: five links in, five links out."""
        chain = [{"provider": "openai", "model": f"backup-{i}"} for i in range(5)]
        _, written = self._saved(monkeypatch, "", "", True, chain=chain)
        assert len(written["chat_fallback"]["chain"]) == 5

    def test_incomplete_links_are_dropped_but_the_rest_survive(self, monkeypatch):
        """One half-filled row shouldn't block saving the good ones."""
        _, written = self._saved(
            monkeypatch, "", "", True,
            chain=[{"provider": "openai", "model": "backup-1"},
                   {"provider": "qianfan", "model": ""},
                   {"provider": "", "model": "orphan"}],
        )
        assert written["chat_fallback"]["chain"] == [
            {"provider": "openai", "model": "backup-1"}
        ]

    def test_an_untouched_row_is_dropped_rather_than_rejected(self, monkeypatch):
        """A row the user added and never filled in is not an error."""
        _, written = self._saved(
            monkeypatch, "", "", True,
            chain=[{"provider": "", "model": ""},
                   {"provider": "openai", "model": "backup-1"}],
        )
        assert written["chat_fallback"]["chain"] == [
            {"provider": "openai", "model": "backup-1"}
        ]

    def test_a_non_list_chain_is_rejected(self, monkeypatch):
        result, _ = self._saved(monkeypatch, "", "", True, chain="openai/backup")
        assert "error" in result

    def test_the_legacy_two_argument_call_still_works(self, monkeypatch):
        """An older client sending one provider/model pair gets a one-link
        chain, so it keeps working against the new config."""
        _, written = self._saved(monkeypatch, "openai", "backup-model", True)
        assert written["chat_fallback"] == {
            "enabled": True,
            "chain": [{"provider": "openai", "model": "backup-model"}],
        }

    def test_provider_models_is_a_list_per_provider(self, monkeypatch):
        """The console's model picker calls .slice() on provider_models[id],
        so each value must be a list — not the richer PROVIDER_MODELS entry
        ({label, models, ...}) it is derived from."""
        monkeypatch.setattr(
            "channel.web.api.models.conf", lambda: {"model": "deepseek-v4-flash"}
        )
        from channel.web.core import providers
        from channel.web.api.models import ModelsHandler

        cap = ModelsHandler._chat_fallback_capability({})
        provider_models = cap["provider_models"]
        assert provider_models, "expected a non-empty model catalog"
        for pid, models in provider_models.items():
            assert isinstance(models, list), f"{pid} -> {type(models).__name__}"
            for m in models:
                assert isinstance(m, str), f"{pid} has a non-string model: {m!r}"
        # Spot-check that the lists were really lifted out of the catalog.
        assert isinstance(
            providers.PROVIDER_MODELS["openai"], dict
        ), "PROVIDER_MODELS entries are dicts — hence the reduction"
        assert "gpt-4o" in provider_models["openai"]

    def test_the_capability_exposes_the_saved_chain(self, monkeypatch):
        monkeypatch.setattr(
            "channel.web.api.models.conf", lambda: {"model": "deepseek-v4-flash"}
        )
        from channel.web.api.models import ModelsHandler

        cap = ModelsHandler._chat_fallback_capability({
            "chat_fallback": {
                "enabled": True,
                "chain": [{"provider": "openai", "model": "backup-1"},
                          {"provider": "qianfan", "model": "backup-2"}],
            }
        })
        assert cap["chain"] == [
            {"provider": "openai", "model": "backup-1"},
            {"provider": "qianfan", "model": "backup-2"},
        ]

    def test_a_legacy_config_is_reported_as_a_one_link_chain(self, monkeypatch):
        """An old config.json must still show its backup model in the UI."""
        monkeypatch.setattr(
            "channel.web.api.models.conf", lambda: {"model": "deepseek-v4-flash"}
        )
        from channel.web.api.models import ModelsHandler

        cap = ModelsHandler._chat_fallback_capability({
            "chat_fallback": {"enabled": True, "provider": "openai", "model": "backup-1"}
        })
        assert cap["chain"] == [{"provider": "openai", "model": "backup-1"}]
