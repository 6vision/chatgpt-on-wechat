"""McpClient resolves a transport the same way the console validates one."""

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
    transport_key = _client(transport, has_url).transport
    assert transport_key == normalize_transport(transport, has_url=has_url)
    assert transport_key in {"stdio", "sse", "streamable-http"}


def test_an_absent_type_defaults_to_stdio():
    assert McpClient({"name": "probe"}).transport == "stdio"


def test_an_unrecognised_type_is_left_for_initialize_to_report():
    # initialize() reports it; one bad entry must not break the loader.
    client = _client("bogus", True)
    assert client.transport == "bogus"
    with pytest.raises(McpConfigError):
        normalize_transport("bogus", has_url=True)
