import pytest
from agent.tools.web_search import web_search as ws


@pytest.mark.parametrize('value', ['false', 'off', '0', [], {'invalid': True}, 1])
def test_anonymous_search_requires_boolean_opt_in(monkeypatch, value):
    monkeypatch.setattr(ws, '_get_api_key', lambda provider: '')
    monkeypatch.setattr(ws, '_get_searxng_url', lambda: '')
    monkeypatch.setattr(ws, 'conf', lambda: {'tools': {'web_search': {'anysearch_anonymous': value, 'keenable_anonymous': value}}})
    assert ws.configured_providers() == []


def test_explicit_opt_in_and_api_key_configuration_remain_supported(monkeypatch):
    monkeypatch.setattr(ws, '_get_api_key', lambda provider: 'fake-key' if provider == 'tavily' else '')
    monkeypatch.setattr(ws, '_get_searxng_url', lambda: '')
    monkeypatch.setattr(ws, 'conf', lambda: {'tools': {'web_search': {'anysearch_anonymous': True, 'keenable_anonymous': True}}})
    assert ws.configured_providers() == ['anysearch', 'tavily', 'keenable']
