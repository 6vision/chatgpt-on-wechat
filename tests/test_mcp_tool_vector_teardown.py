"""A retired MCP server must not leave its description vectors behind."""

import threading
import types

import pytest


def _vec(text):
    """A crude direction embedding: which topic words the text mentions.

    Enough to tell a vector computed from the wrong description apart from one
    computed from the right one, without a model.
    """
    return [float(text.lower().count(w))
            for w in ("wiki", "search", "ledger", "payments", "spooler")]


def _tool(name, server, description):
    return types.SimpleNamespace(name=name, server_name=server,
                                 description=description, input_schema={})


@pytest.fixture
def manager():
    """A ToolManager with an observable embedding provider."""
    from agent.tools.tool_manager import ToolManager

    handle = ToolManager.__new__(ToolManager)
    handle._mcp_tool_instances = {}
    handle._mcp_tool_vectors = {}
    handle._mcp_status = {}
    handle._mcp_vector_lock = threading.RLock()
    handle._mcp_registry = types.SimpleNamespace(
        _registry_lock=threading.RLock(),
        _clients={},
        _shared_pool={},
        _shared_pool_lock=threading.RLock(),
    )
    handle.embedded = []
    handle._get_embedding_provider = lambda: types.SimpleNamespace(
        embed_batch=lambda texts: (handle.embedded.extend(texts)
                                   or [_vec(t) for t in texts]),
        embed_query=_vec,
    )
    return handle


def _publish(manager, name, server, description):
    manager._mcp_tool_instances[name] = _tool(name, server, description)


# --- the gap ----------------------------------------------------------------


def test_teardown_drops_the_vectors_of_the_tools_it_retires(manager):
    _publish(manager, "search", "alpha", "search the internal wiki")
    _publish(manager, "ledger", "alpha", "query the payments ledger")
    _publish(manager, "notes", "beta", "take notes")
    manager._mcp_status = {"alpha": "running", "beta": "running"}
    manager._ensure_mcp_tool_vectors()
    assert set(manager._mcp_tool_vectors) == {"search", "ledger", "notes"}

    manager._teardown_mcp_server("alpha")

    assert "search" not in manager._mcp_tool_vectors, "a stale vector outlived its tool"
    assert "ledger" not in manager._mcp_tool_vectors
    assert "notes" in manager._mcp_tool_vectors, "another server's vector must survive"


def test_a_tool_republished_under_the_same_name_is_re_embedded(manager):
    # The reload shape: alpha is torn down, then beta publishes `search` with a
    # different description. Before the fix the new tool inherited the old
    # description's embedding, because the name was already cached.
    _publish(manager, "search", "alpha", "search the internal wiki and index")
    manager._ensure_mcp_tool_vectors()
    manager.embedded.clear()

    manager._teardown_mcp_server("alpha")
    _publish(manager, "search", "beta", "restart the print spooler")

    manager._ensure_mcp_tool_vectors()

    assert manager.embedded == ["search: restart the print spooler"], (
        "the vector was reused from the retired description"
    )
    assert manager._mcp_tool_vectors["search"] == _vec("search: restart the print spooler")


def test_a_stale_vector_no_longer_wins_a_query_it_cannot_answer(manager):
    _publish(manager, "search", "alpha", "search the internal wiki and index")
    manager._ensure_mcp_tool_vectors()

    manager._teardown_mcp_server("alpha")
    _publish(manager, "search", "beta", "restart the print spooler")
    _publish(manager, "query_ledger", "beta", "query the payments ledger")
    manager._ensure_mcp_tool_vectors()

    query = _vec("reconcile the payments ledger for last quarter")
    scores = {name: sum(a * b for a, b in zip(vec, query))
              for name, vec in manager._mcp_tool_vectors.items()}

    assert max(scores, key=scores.get) == "query_ledger", (
        f"the spooler tool won with a stale vector's score: {scores}"
    )


def test_the_vector_cache_shrinks_when_a_tool_disappears(manager):
    # A loader that failed part way through publishing can leave an entry with
    # no tool behind it. Teardown attributes by server, so this is the only
    # place that can catch it.
    _publish(manager, "search", "alpha", "search the internal wiki")
    manager._ensure_mcp_tool_vectors()
    assert "search" in manager._mcp_tool_vectors

    del manager._mcp_tool_instances["search"]
    manager._ensure_mcp_tool_vectors()

    assert "search" not in manager._mcp_tool_vectors


def test_the_cache_does_not_grow_across_reload_cycles(manager):
    seen_sizes = []
    for cycle in range(3):
        _publish(manager, f"tool_{cycle}", "alpha", f"description {cycle}")
        manager._ensure_mcp_tool_vectors()
        manager._teardown_mcp_server("alpha")
        manager._ensure_mcp_tool_vectors()
        seen_sizes.append(len(manager._mcp_tool_vectors))

    assert seen_sizes == [0, 0, 0], f"the cache grew across reloads: {seen_sizes}"


# --- unchanged behaviour ----------------------------------------------------


def test_a_healthy_tool_keeps_its_vector_across_a_reload(manager):
    _publish(manager, "search", "alpha", "search the internal wiki")
    manager._ensure_mcp_tool_vectors()
    original = dict(manager._mcp_tool_vectors)

    _publish(manager, "notes", "alpha", "take notes")
    manager._ensure_mcp_tool_vectors()

    assert manager._mcp_tool_vectors["search"] == original["search"], (
        "an unchanged tool must not be re-embedded on every turn"
    )


def test_teardown_of_an_unknown_server_is_a_no_op(manager):
    _publish(manager, "search", "alpha", "search the internal wiki")
    manager._ensure_mcp_tool_vectors()

    manager._teardown_mcp_server("never-registered")

    assert "search" in manager._mcp_tool_vectors
    assert "search" in manager._mcp_tool_instances


def test_a_server_with_no_vectors_yet_tears_down_cleanly(manager):
    _publish(manager, "search", "alpha", "search the internal wiki")
    manager._teardown_mcp_server("alpha")  # never embedded

    assert "search" not in manager._mcp_tool_instances
    assert manager._mcp_tool_vectors == {}
