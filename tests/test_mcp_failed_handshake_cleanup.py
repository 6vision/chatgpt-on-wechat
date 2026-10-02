# encoding:utf-8
"""A stdio MCP server that fails the handshake must not leave its process behind.

``_init_stdio`` spawns the child process and starts the two reader threads
*before* the handshake, then just returns whatever ``_handshake()`` says. A
server that answers ``initialize`` with a JSON-RPC error, or that exits without
answering at all, therefore makes ``initialize()`` return False with the
subprocess and both reader threads still live -- and nothing downstream will
ever clean them up: ``start_all()`` only logs "failed to initialize --
skipping" and drops the client on the floor. Every reload of an ``mcp.json``
holding one such server therefore accumulates another orphaned ``node``/``npx``
process plus two threads, and on Windows those hold their console pipes open
forever.

These tests pin that a failed handshake tears the child down through the same
``shutdown()`` helper a normal teardown uses, exactly once, and that a
*successful* handshake is left alone.
"""

import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.mcp import mcp_client as mcp_client_module
from agent.tools.mcp.mcp_client import McpClient


class _FakePipe:
    """Stands in for one of the child's three pipes.

    Iterating it replays ``lines`` and then stops, which is what a real pipe
    does at EOF -- so a fake that yields nothing models a server that exits
    without answering, and one that yields a JSON line models a live server.
    """

    def __init__(self, lines=()):
        self._lines = list(lines)
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
    """Stands in for the ``subprocess.Popen`` handle a stdio server would be.

    Counts ``terminate``/``kill`` so a test can prove the teardown ran, and
    reports itself alive until one of them is called, which is what makes the
    leak observable.
    """

    def __init__(self, stdout_lines=(), stderr_lines=()):
        self.pid = 4242
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


def _config(name):
    return {"name": name, "type": "stdio", "command": "node", "args": ["server.js"]}


def _wait_for(predicate, bound=5.0):
    """Poll ``predicate`` until true or ``bound`` elapses, then return its value.

    The reader threads are real threads, so their exit is asynchronous; the
    bound keeps a regression from hanging the suite instead of failing it.
    """
    deadline = time.monotonic() + bound
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _reader_threads(name):
    return [t for t in threading.enumerate() if t.name.endswith(name) and t.is_alive()]


class FailedHandshakeTearsDownTheChildTest(unittest.TestCase):
    """A child left running by a failed handshake is an orphan nobody reaps."""

    def _run(self, stdout_lines):
        """Boot a client whose handshake fails, returning (client, proc)."""
        client = McpClient(_config("broken"))
        proc = _FakeProc(stdout_lines)
        with patch.object(mcp_client_module.subprocess, "Popen", return_value=proc):
            self.assertFalse(client.initialize())
        return client, proc

    def test_server_that_exits_without_answering_is_terminated(self):
        """A server that closes stdout instead of answering ``initialize`` must
        not survive the handshake attempt."""
        client, proc = self._run([])

        self.assertIsNone(
            client._proc,
            "the child process is still attached after a failed handshake; "
            "start_all() drops this client without ever calling shutdown(), so "
            "every reload of a broken server leaks another node process",
        )
        self.assertEqual(proc.terminate_calls, 1)
        self.assertTrue(proc.stdin.closed)

    def test_jsonrpc_error_response_is_terminated(self):
        """The same has to hold for the other failure shape: the server speaks
        the protocol well enough to refuse, answering with a JSON-RPC error."""
        client, proc = self._run(
            ['{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"no"}}\n']
        )

        self.assertIsNone(client._proc)
        self.assertEqual(proc.terminate_calls, 1)

    def test_both_reader_threads_are_gone_after_a_failed_handshake(self):
        """The drain threads iterate the child's pipes, so they only end once
        the child is dead; each reload of a broken server was leaving two more
        behind."""
        self._run([])
        self.assertTrue(
            _wait_for(lambda: not _reader_threads("-broken")),
            "reader threads are still running: %r" % (threading.enumerate(),),
        )

    def test_teardown_is_not_repeated_by_a_later_shutdown(self):
        """The cleanup goes through the shared ``shutdown()`` helper, which
        other paths (``_teardown_mcp_server``, ``shutdown_all``) call too, so it
        has to stay a single idempotent teardown rather than a second one."""
        client, proc = self._run([])
        client.shutdown()
        client.shutdown()

        self.assertEqual(proc.terminate_calls, 1)
        self.assertEqual(proc.kill_calls, 0)

    def test_successful_handshake_keeps_the_child_running(self):
        """The guard on the guard: only a *failed* handshake may stop the child,
        or every healthy server would be killed the moment it came up."""
        client = McpClient(_config("healthy"))
        proc = _FakeProc([
            '{"jsonrpc":"2.0","id":%d,"result":{"protocolVersion":"2024-11-05"}}\n'
            % client._next_id
        ])
        with patch.object(mcp_client_module.subprocess, "Popen", return_value=proc):
            self.assertTrue(client.initialize())

        self.assertIs(client._proc, proc)
        self.assertIsNone(proc.poll())
        self.assertEqual(proc.terminate_calls, 0)


if __name__ == "__main__":
    unittest.main()
