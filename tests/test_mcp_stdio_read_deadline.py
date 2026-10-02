# encoding:utf-8
"""A stdio MCP read must be bounded by total time, not by time per line read.

``_readline_with_timeout`` bounds a single ``queue.get()``, and ``_stdio_send``
calls it in a loop that skips anything carrying no ``id`` -- notifications,
stale responses, blank lines. So the effective timeout is *per skipped line*:
a server that streams ``notifications/message`` while it works (progress
reporting, log forwarding -- routine during a long tool call) keeps satisfying
``queue.get()`` instantly, the budget resets on every line, and the request
never times out. A server that simply never answers then hangs ``call_tool``
forever, holding ``_call_lock``, with no ``TimeoutError`` and no cancel point:
the tool call never returns and the agent waits on it indefinitely.

The SSE path already learned this lesson -- ``_sse_discover_endpoint`` runs on a
monotonic deadline for the same reason. These tests pin the stdio path to one
total budget per request, and pin that a response which arrives in time is still
read, so the bound cannot be met by bailing out on the first notification.

Budgets here are whole seconds on purpose: ``McpClient.__init__`` coerces the
configured timeout with ``int(...)``, so a fractional budget would silently
become zero and make every ``queue.get`` expire instantly -- which reads as a
pass while testing nothing.
"""

import json
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.mcp import mcp_client as mcp_client_module
from agent.tools.mcp.mcp_client import McpClient


# One second of budget per request, and a join bound well above it: only a
# correct implementation returns in time, so a regression fails an assertion
# instead of hanging the suite.
_BUDGET = 1
_WAIT_BOUND = 6


class _FakePipe:
    """A child's pipe. Iterating it replays ``lines`` -- a generator models a
    server that talks for a while, an empty tuple models a mute one."""

    def __init__(self, lines=()):
        self._lines = lines
        self.written = []
        self.closed = False

    def __iter__(self):
        return iter(self._lines)

    def write(self, data):
        self.written.append(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class _FakeProc:
    """Stands in for the ``subprocess.Popen`` handle of a live stdio server."""

    def __init__(self, stdout_lines=(), stderr_lines=()):
        self.pid = 6161
        self.stdin = _FakePipe()
        self.stdout = _FakePipe(stdout_lines)
        self.stderr = _FakePipe(stderr_lines)
        self.terminate_calls = 0
        self.kill_calls = 0
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminate_calls += 1
        self._alive = False

    def kill(self):
        self.kill_calls += 1
        self._alive = False

    def wait(self, timeout=None):
        self._alive = False
        return 0


def _client(timeout=_BUDGET, name="chatty"):
    client = McpClient(
        {"name": name, "type": "stdio", "command": "node", "timeout": timeout}
    )
    client._proc = _FakeProc()
    client._initialized = True
    return client


def _notification():
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {"level": "info", "data": "still working"},
        }
    ) + "\n"


def _sent_request_id(client):
    """The id of the request the client actually wrote to the pipe.

    Read back off the pipe rather than guessed from ``_next_id``: the id is
    allocated while the request is built, so the counter has already moved on
    by the time a test gets to look at it.
    """
    return json.loads(client._proc.stdin.written[-1])["id"]


def _response(request_id, text="pong"):
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"content": [{"type": "text", "text": text}]},
        }
    ) + "\n"


class StdioReadIsBoundedByTotalTimeTest(unittest.TestCase):
    """One request gets one time budget, however chatty the server is."""

    def setUp(self):
        self._stoppers = []

    def tearDown(self):
        for stop in self._stoppers:
            stop()

    def _feed_notifications(self, client, interval=0.01):
        """Keep pushing notification lines, the way a progress-reporting server
        does while a long tool call runs."""
        stop = threading.Event()

        def feed():
            while not stop.is_set():
                client._read_queue.put(_notification())
                time.sleep(interval)

        thread = threading.Thread(target=feed, daemon=True)
        thread.start()
        self._stoppers.append(stop.set)
        return stop

    def _run_bounded(self, target):
        """Run ``target`` on a thread; return (result, error, elapsed, alive).

        The bound is what turns "hangs forever" into a failed assertion instead
        of a hung suite.
        """
        results, errors = [], []

        def run():
            try:
                results.append(target())
            except BaseException as exc:  # recorded, then asserted on
                errors.append(exc)

        started = time.monotonic()
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(timeout=_WAIT_BOUND)
        return (
            results[0] if results else None,
            errors[0] if errors else None,
            time.monotonic() - started,
            thread.is_alive(),
        )

    def test_chatty_server_that_never_answers_is_cut_off(self):
        """The defect: every notification it skips resets the read timeout, so
        a server that never answers the tool call hangs the request."""
        client = _client()
        self._feed_notifications(client)

        result, _error, elapsed, alive = self._run_bounded(lambda: client.call_tool("ping", {}))

        self.assertFalse(
            alive,
            "call_tool never returned: every notification line it skips resets "
            "the read timeout, so the request has no total time bound",
        )
        self.assertLess(
            elapsed, _BUDGET + 2,
            "the request must end near its configured budget, not whenever the "
            "server happens to stop talking",
        )
        self.assertIn("timed out", result)

    def test_a_flooding_server_cannot_hang_the_handshake(self):
        """The same bound has to cover the initialize exchange: a server that
        floods notifications and never completes the handshake used to wedge
        the loader thread that started it."""
        client = McpClient(
            {"name": "flooder", "type": "stdio", "command": "node", "timeout": _BUDGET}
        )

        def flood_for(seconds):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                yield _notification()
                time.sleep(0.01)

        # Six seconds of chatter against a one-second budget: a per-line budget
        # survives all of it and only trips once the flood stops.
        proc = _FakeProc(stdout_lines=flood_for(6.0))
        with patch.object(mcp_client_module.subprocess, "Popen", return_value=proc):
            result, _error, elapsed, alive = self._run_bounded(client.initialize)

        self.assertFalse(
            alive,
            "initialize() never returned: the notifications it skips keep "
            "resetting the read timeout on the same pipe",
        )
        self.assertLess(
            elapsed, _BUDGET + 2,
            "the handshake must be cut off by its own budget, not by the server "
            "eventually falling silent",
        )
        self.assertIs(result, False)

    def test_stdio_send_raises_a_named_timeout_error(self):
        """Below ``call_tool``'s catch-all the failure must be a real
        TimeoutError naming the server, so a caller can tell a hung server from
        a broken one and the agent can report which server went quiet."""
        client = _client()
        self._feed_notifications(client)

        _result, error, _elapsed, _alive = self._run_bounded(
            lambda: client._stdio_send({"jsonrpc": "2.0", "id": 1, "method": "tools/call"})
        )

        self.assertIsInstance(error, TimeoutError)
        self.assertIn("chatty", str(error))

    def test_silent_server_is_still_bounded(self):
        """The pre-existing behaviour has to survive the change: a server that
        says nothing at all still trips the timeout."""
        client = _client()

        result, _error, _elapsed, alive = self._run_bounded(lambda: client.call_tool("ping", {}))

        self.assertFalse(alive)
        self.assertIn("timed out", result)

    def test_notifications_do_not_break_a_response_that_arrives_in_time(self):
        """Notifications are legitimate -- a server routinely streams them and
        then answers. Bailing on the first one would satisfy the tests above
        while breaking every real long-running tool call."""
        client = _client(timeout=20)
        self._feed_notifications(client)

        def answer_when_ready():
            while not client._proc.stdin.written:
                time.sleep(0.01)
            time.sleep(0.3)
            client._read_queue.put(_response(_sent_request_id(client)))

        threading.Thread(target=answer_when_ready, daemon=True).start()
        result, error, _elapsed, _alive = self._run_bounded(lambda: client.call_tool("ping", {}))

        self.assertIsNone(error, f"unexpected failure: {error!r}")
        self.assertEqual(result, "pong")


if __name__ == "__main__":
    unittest.main()
