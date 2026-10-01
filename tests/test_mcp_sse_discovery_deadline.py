"""SSE endpoint discovery must be bounded by total time, not by per-read time.

urlopen()'s ``timeout`` bounds a single socket read, and every arriving byte
resets it. A server that holds the stream open with keepalive comments
(": keepalive") therefore keeps the discovery loop alive forever, and the loader
walks its servers serially on one background thread -- so every server queued
behind the stuck one stays "pending" and its tools are silently missing from
the agent, with no timeout and no error anywhere. These tests pin a total
deadline on that loop, and pin that a server which does send its endpoint event
in time is still discovered normally.
"""

import threading
import time
from unittest.mock import patch

from agent.tools.mcp import mcp_client
from agent.tools.mcp.mcp_client import McpClient


# Nothing but the total deadline can end the loop below, so the thread is
# joined against a bound far above it: a regression fails an assertion instead
# of hanging the suite. The thread is a daemon for the same reason.
_WAIT_BOUND = 30


class _FakeStream:
    """Stand-in for the object urlopen() returns when opening an SSE stream.

    ``lines`` is replayed first, then the stream either ends (a server that
    goes quiet) or emits keepalive comments forever, which is what a real
    server does to hold the connection open between events. ``delay`` is the
    pause before each line, so a test can make an otherwise instant server
    arrive slowly.
    """

    def __init__(self, lines=(), *, keepalive=False, delay=0.0):
        self._lines = list(lines)
        self._keepalive = keepalive
        self._delay = delay
        self.lines_read = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        for line in self._lines:
            self.lines_read += 1
            if self._delay:
                time.sleep(self._delay)
            yield line
        while self._keepalive:
            self.lines_read += 1
            if self._delay:
                time.sleep(self._delay)
            yield b": keepalive\n"


def _client():
    client = McpClient({"name": "test", "type": "sse", "url": "http://mcp.test/sse"})
    client._sse_url = "http://mcp.test/sse"
    return client


def test_keepalive_only_stream_is_cut_off_by_the_total_deadline():
    """A stream that only ever keepalives must not be able to outlive the
    deadline: each of its lines resets the per-read socket timeout, so without
    a deadline of its own the loop below never returns."""
    client = _client()
    errors = []

    def discover():
        try:
            client._sse_discover_endpoint()
        except BaseException as exc:  # recorded, then asserted on below
            errors.append(exc)

    with patch("urllib.request.urlopen", return_value=_FakeStream(keepalive=True, delay=0.02)):
        thread = threading.Thread(target=discover, daemon=True)
        started = time.monotonic()
        thread.start()
        thread.join(timeout=_WAIT_BOUND)
        elapsed = time.monotonic() - started

    assert not thread.is_alive(), (
        "SSE endpoint discovery never returned: the keepalive stream resets the "
        "per-read socket timeout forever, so the loop needs its own total deadline"
    )
    assert elapsed < _WAIT_BOUND
    assert len(errors) == 1, f"expected one failure, got {errors!r}"
    assert isinstance(errors[0], TimeoutError)
    assert "endpoint" in str(errors[0])


def test_discovery_failure_is_reported_to_the_caller():
    """The deadline must surface as a normal initialization failure carrying a
    reason, so the server is marked failed instead of being left pending."""
    client = _client()
    client._handshake = lambda: True

    with patch("urllib.request.urlopen", return_value=_FakeStream(keepalive=True, delay=0.02)):
        thread = threading.Thread(target=client.initialize, daemon=True)
        thread.start()
        thread.join(timeout=_WAIT_BOUND)

    assert not thread.is_alive()
    assert client._post_url is None


def test_endpoint_event_is_discovered_before_the_deadline():
    """A server that sends its endpoint event is still discovered, and the
    relative URI is resolved against the SSE base."""
    client = _client()
    stream = _FakeStream([
        b": keepalive\n",
        b"event: endpoint\n",
        b"data: /messages?sessionId=abc\n",
    ])

    with patch("urllib.request.urlopen", return_value=stream):
        endpoint = client._sse_discover_endpoint()

    assert endpoint == "http://mcp.test/messages?sessionId=abc"
    assert stream.lines_read == 3


def test_keepalives_do_not_break_discovery_that_finishes_in_time(monkeypatch):
    """Keepalives are legitimate, so bailing on the first one would satisfy the
    test above while breaking every real server, which warms the stream for a
    few seconds before announcing its endpoint."""
    monkeypatch.setattr(mcp_client, "_SSE_DISCOVERY_TIMEOUT", 5)
    client = _client()
    stream = _FakeStream(
        [b": keepalive\n", b": keepalive\n", b"data: /messages?sessionId=abc\n"],
        delay=0.05,
    )

    with patch("urllib.request.urlopen", return_value=stream):
        endpoint = client._sse_discover_endpoint()

    assert endpoint == "http://mcp.test/messages?sessionId=abc"


def test_shipped_deadline_stays_within_the_transport_timeouts():
    """The default has to stay small enough that one unresponsive server
    cannot hold up the servers behind it for long; the other HTTP calls in
    this module top out at 30s."""
    assert 0 < mcp_client._SSE_DISCOVERY_TIMEOUT <= 30
