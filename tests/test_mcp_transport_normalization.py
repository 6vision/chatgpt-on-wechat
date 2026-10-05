"""McpClient must resolve a transport the way the console validates one.

`service.normalize_transport` is the single decision: it strips whitespace,
folds case, maps the four streamable-http aliases onto one key, and defaults an
absent type by whether a url is present. `validate_server` stores what it
returns, so anything saved through the console is already canonical.

A hand-edited mcp.json does not pass validate_server -- `ToolManager`
normalizes the *shape* (list vs dict) and nothing else -- so the client is the
last place the value is interpreted. It used to fold only the bare aliases,
which left a padded `"  http  "` or an empty `"type": ""` as a transport
`initialize()` does not recognise: logged as an unknown transport, never
booted, and the same on every start because nothing rewrites the file.
"""

import pytest

from agent.tools.mcp.mcp_client import McpClient
from agent.tools.mcp.service import McpConfigError, normalize_transport


# (label, type as written in mcp.json, whether the entry has a url)
SPELLINGS = [
    ("canonical", "streamable-http", True),
    ("bare alias", "http", True),
    ("underscore alias", "streamable_http", True),
    ("squashed alias", "streamablehttp", True),
    ("uppercase", "STREAMABLE-HTTP", True),
    ("padded alias", "  http  ", True),
    ("empty with url", "", True),
    ("empty without url", "", False),
    ("explicit stdio", "stdio", False),
    ("explicit sse", "sse", True),
]


def _client(transport, has_url):
    cfg = {"name": "probe"}
    if transport is not None:
        cfg["type"] = transport
    if has_url:
        cfg["url"] = "https://example.test/mcp"
    return McpClient(cfg)


@pytest.mark.parametrize(
    "label,transport,has_url", SPELLINGS, ids=[s[0] for s in SPELLINGS]
)
def test_client_transport_matches_the_validator(label, transport, has_url):
    assert _client(transport, has_url).transport == normalize_transport(
        transport, has_url=has_url
    )


@pytest.mark.parametrize(
    "label,transport,has_url", SPELLINGS, ids=[s[0] for s in SPELLINGS]
)
def test_every_spelling_lands_on_a_transport_initialize_knows(
    label, transport, has_url
):
    # initialize() dispatches on exactly these three, and logs "Unknown
    # transport type" for anything else -- which is what a padded or empty type
    # used to produce.
    assert _client(transport, has_url).transport in {
        "stdio", "sse", "streamable-http",
    }


def test_an_absent_type_defaults_to_stdio():
    # `McpClient.__init__` reads config.get("type", "stdio") before normalizing,
    # so an absent type never reaches the url-based default the validator would
    # apply. Pin the behaviour that follows rather than leaving it implied: a
    # server with no type and no command is a broken entry either way, and
    # ToolManager._normalize_mcp_configs already fills in "sse" when a url is
    # present before the client ever sees it.
    assert McpClient({"name": "probe"}).transport == "stdio"


def test_an_unrecognised_type_is_left_for_initialize_to_report():
    # The validator raises McpConfigError here. The constructor must not: it is
    # also reached from the background loader, where one bad entry should not
    # take down every other server. initialize() logs and returns False.
    client = _client("bogus", True)
    assert client.transport == "bogus"
    with pytest.raises(McpConfigError):
        normalize_transport("bogus", has_url=True)


def test_the_validator_is_the_only_copy_of_the_alias_table():
    # mcp_client used to keep its own frozenset of the same four spellings; two
    # copies is how they drifted. It now imports the decision instead.
    import agent.tools.mcp.mcp_client as client_mod

    assert not hasattr(client_mod, "_STREAMABLE_HTTP_ALIASES")
