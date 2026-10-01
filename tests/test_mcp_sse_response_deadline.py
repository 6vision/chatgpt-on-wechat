"""Reading an MCP SSE response must be bounded by total time, not per-read time.

urlopen()'s ``timeout`` bounds a single socket read, and every arriving byte
resets it. A server that streams keepalive comments (": keepalive", which
servers send every few seconds to hold the connection open) but never sends the
awaited JSON-RPC response therefore keeps the read loop in
``_read_sse_response`` alive forever: the tool call never returns, the
connection is never closed, and the calling task is stuck. These tests pin a
total deadline on that loop, and pin that a response which does arrive in time
is still delivered -- including one that only arrives after keepalives, or
after notifications and unrelated ids the loop has to skip.
"""

import threading
import time
from unittest.mock import patch

from agent.tools.mcp.mcp_client import McpClient


# Only a total deadline can end the keepalive loop below, so the thread is
# joined against a bound far above it: a regression fails an assertion instead
# of hanging the suite. The thread is a daemon for the same reason, and the
# stream is stopped explicitly so a failing run does not leave it spinning.
_WAIT_BOUND = 5


class _FakeStream:
    """Stand-in for the SSE stream a POST to an MCP server may return.

    ``lines`` is replayed first, then the stream either ends (a server that
    goes quiet) or emits keepalive comments forever, which is what a real
    server does to hold the connection open between events. ``delay`` is the
    pause before each line, so a test can make an otherwise instant server
    arrive slowly.
    """

    def __init__(self, lines=(), *, keepalive=False, delay=0.0, content_type="text/event-stream"):
        self._lines = list(lines)
        self._keepalive = keepalive
        self._delay = delay
        self.stop = threading.Event()
        self.content_type = content_type
        self.status = 200
        self.lines_read = 0
        self.headers = {"Content-Type": content_type, "Mcp-Session-Id": "s1"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b""

    def __iter__(self):
        for line in self._lines:
            self.lines_read += 1
            if self._delay:
                time.sleep(self._delay)
            yield line
        while self._keepalive and not self.stop.is_set():
            self.lines_read += 1
            if self._delay:
                time.sleep(self._delay)
            yield b": keepalive\n"


def _client(**config):
    cfg = {"name": "test", "type": "streamable-http", "url": "http://mcp.test"}
    cfg.update(config)
    client = McpClient(cfg)
    client._http_url = "http://mcp.test"
    client._initialized = True
    return client


def _run_in_thread(fn, stream):
    """Call ``fn``, bounded, and return (finished_in_time, elapsed, errors)."""
    errors = []

    def target():
        try:
            fn()
        except BaseException as exc:  # recorded, then asserted on below
            errors.append(exc)

    thread = threading.Thread(target=target, daemon=True)
    started = time.monotonic()
    thread.start()
    try:
        thread.join(timeout=_WAIT_BOUND)
        finished = not thread.is_alive()
        elapsed = time.monotonic() - started
    finally:
        stream.stop.set()
        thread.join(timeout=_WAIT_BOUND)
    return finished, elapsed, errors


def test_keepalive_only_stream_is_cut_off_by_the_total_deadline():
    """A stream that only ever keepalives must not be able to outlive the
    deadline: each of its lines resets the per-read socket timeout, so without
    a deadline of its own the loop below never returns."""
    client = _client(timeout=1)
    stream = _FakeStream(keepalive=True, delay=0.01)

    finished, _elapsed, errors = _run_in_thread(
        lambda: client._read_sse_response(stream, 7), stream
    )

    assert finished, (
        "reading the SSE response never returned: the keepalive stream resets "
        "the per-read socket timeout forever, so the loop needs its own total "
        "deadline"
    )
    assert len(errors) == 1, f"expected one failure, got {errors!r}"
    assert isinstance(errors[0], TimeoutError)
    assert "timed out after 1s" in str(errors[0])


def test_explicit_timeout_overrides_the_per_server_default():
    """The deadline has to be overridable per call, like
    ``_readline_with_timeout``, so a caller that knows it is waiting on
    something short is not stuck with the per-server budget."""
    client = _client(timeout=120)
    stream = _FakeStream(keepalive=True, delay=0.01)

    finished, _elapsed, errors = _run_in_thread(
        lambda: client._read_sse_response(stream, 7, timeout=0.2), stream
    )

    assert finished, "an explicit timeout did not bound the SSE read"
    assert len(errors) == 1, f"expected one failure, got {errors!r}"
    assert isinstance(errors[0], TimeoutError)
    assert "timed out after 0.2s" in str(errors[0])


def test_response_arriving_before_the_deadline_is_returned():
    """A response that arrives in time must come back unchanged and promptly:
    the deadline is a bound, not a delay."""
    client = _client(timeout=5)
    stream = _FakeStream(
        [
            b": keepalive\n",
            b'event: message\n',
            b'data: {"jsonrpc": "2.0", "id": 7, "result": {"content": []}}\n',
            b"\n",
        ],
        delay=0.01,
    )

    started = time.monotonic()
    msg = client._read_sse_response(stream, 7)
    elapsed = time.monotonic() - started

    assert msg == {"jsonrpc": "2.0", "id": 7, "result": {"content": []}}
    assert stream.lines_read == 4, "the loop kept reading past the response"
    assert elapsed < 5, "a complete response waited for the whole deadline"


def test_keepalives_before_the_response_do_not_count_as_a_failure():
    """Keepalives are legitimate, so bailing on the first one would satisfy the
    test above while breaking every real server, which warms the stream for a
    few seconds before sending the response."""
    client = _client(timeout=5)
    stream = _FakeStream([b": keepalive\n"] * 5 + [
        b'data: {"jsonrpc": "2.0", "id": 7, "result": "ok"}\n',
        b"\n",
    ], delay=0.01)

    msg = client._read_sse_response(stream, 7)

    assert msg["result"] == "ok"


def test_notifications_and_unrelated_ids_are_skipped_until_the_match():
    """The stream carries traffic the loop must ignore before the awaited id
    shows up; skipping it has to keep working under the deadline."""
    client = _client(timeout=5)
    stream = _FakeStream(
        [
            b'data: {"jsonrpc": "2.0", "method": "notifications/progress"}\n',
            b"\n",
            b'data: not json\n',
            b"\n",
            b'data: {"jsonrpc": "2.0", "id": 99, "result": "other"}\n',
            b"\n",
            b'data: {"jsonrpc": "2.0", "id": 7, "result": "mine"}\n',
            b"\n",
        ],
        delay=0.01,
    )

    msg = client._read_sse_response(stream, 7)

    assert msg["result"] == "mine"


def test_a_stream_that_ends_early_still_reports_the_closed_stream():
    """An ended stream is a different failure from a hung one and keeps its own
    error: the deadline must not swallow it by claiming a timeout."""
    client = _client(timeout=5)
    stream = _FakeStream([b": keepalive\n"])

    errors = []
    try:
        client._read_sse_response(stream, 7)
    except BaseException as exc:
        errors.append(exc)

    assert len(errors) == 1, f"expected one failure, got {errors!r}"
    assert isinstance(errors[0], IOError)
    assert not isinstance(errors[0], TimeoutError)
    assert "closed before response" in str(errors[0])


def test_call_tool_reports_the_timeout_instead_of_hanging():
    """The deadline has to survive the real call path: the tool call returns
    an error string rather than blocking forever."""
    client = _client(timeout=1)
    stream = _FakeStream(keepalive=True, delay=0.01)
    results = []

    def urlopen(_request, timeout=None):
        return stream

    def call():
        results.append(client.call_tool("ping", {}))

    with patch("urllib.request.urlopen", side_effect=urlopen):
        finished, _elapsed, _errors = _run_in_thread(call, stream)

    assert finished, "call_tool never returned against a keepalive-only stream"
    assert results == [
        "Error: [MCP:test] streamable-http SSE response read timed out after 1s"
    ]