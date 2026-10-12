"""A POSTed MCP SSE response must not be read without a total budget."""

import json
import time
import urllib.request

import pytest

from agent.tools.mcp import mcp_client as mcp


class _Resp:
    """A response that trickles forever, like a server holding a stream open.

    A real socket read returns once *some* data arrives (at most ``size``
    bytes); it never waits for the body to end. That is exactly what defeats
    ``urlopen``'s per-read timeout.
    """

    def __init__(self, chunk_delay=0.01, body=None):
        self.chunk_delay = chunk_delay
        self._body = body
        self.reads = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        self.closed = True

    def read(self, size=-1, *args, **kwargs):
        self.reads += 1
        if self._body is not None:
            # A fixed body: hand out what is left, then EOF.
            if not self._body:
                return b""
            if size and size > 0:
                chunk, self._body = self._body[:size], self._body[size:]
                return chunk
            body, self._body = self._body, b""
            return body
        time.sleep(self.chunk_delay)
        return b"x" * (size if size and size > 0 else 1)

    def read1(self, size=-1, *args, **kwargs):
        return self.read(size, *args, **kwargs)

    def __iter__(self):
        while True:
            time.sleep(self.chunk_delay)
            yield b": keepalive\n"


@pytest.fixture
def client():
    """An McpClient wired for the SSE transport with a 1s budget."""
    handle = mcp.McpClient.__new__(mcp.McpClient)
    handle.name = "probe"
    handle.transport = "sse"
    handle._sse_url = "http://127.0.0.1:9/sse"
    handle._post_url = "http://127.0.0.1:9/message"
    handle._timeout = 1
    return handle


def _post(client, monkeypatch, resp):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: resp)
    return client._sse_send({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})


# --- the gap ----------------------------------------------------------------


def test_a_trickling_body_is_cut_off_by_the_budget(client, monkeypatch):
    resp = _Resp()
    start = time.monotonic()
    with pytest.raises(TimeoutError) as caught:
        _post(client, monkeypatch, resp)
    elapsed = time.monotonic() - start

    assert "timed out" in str(caught.value)
    assert elapsed < 10, f"the budget did not bound the read ({elapsed:.1f}s)"


def test_the_timeout_names_the_server_and_the_budget(client, monkeypatch):
    with pytest.raises(TimeoutError) as caught:
        _post(client, monkeypatch, _Resp())
    message = str(caught.value)
    assert "probe" in message and "1s" in message


def test_the_body_is_read_in_chunks_not_one_call(client, monkeypatch):
    # A single read() would hand the loop nothing to bound; the fix reads in
    # bounded pieces, so more than one read must happen.
    resp = _Resp()
    with pytest.raises(TimeoutError):
        _post(client, monkeypatch, resp)
    assert resp.reads > 1, "the whole body was read in one blocking call"


def test_a_response_without_read1_is_still_bounded(client, monkeypatch):
    class _NoRead1(_Resp):
        read1 = None

        def read(self, size=-1, *args, **kwargs):
            return super().read(size, *args, **kwargs)

    resp = _NoRead1()
    del _NoRead1.read1
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        _post(client, monkeypatch, resp)
    assert time.monotonic() - start < 10


# --- unchanged behaviour ----------------------------------------------------


def test_a_normal_response_still_parses(client, monkeypatch):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}).encode()
    resp = _Resp(body=payload)
    assert _post(client, monkeypatch, resp) == {"jsonrpc": "2.0", "id": 1,
                                                 "result": {"tools": []}}


def test_an_empty_body_still_raises_the_json_error(client, monkeypatch):
    with pytest.raises(json.JSONDecodeError):
        _post(client, monkeypatch, _Resp(body=b""))


def test_an_oversized_body_is_refused(client, monkeypatch):
    monkeypatch.setattr(mcp, "_SSE_RESPONSE_MAX_BYTES", 1024, raising=False)
    resp = _Resp(body=b"x" * 4096)

    with pytest.raises(IOError) as caught:
        _post(client, monkeypatch, resp)

    assert "exceeded" in str(caught.value)


def test_a_healthy_response_is_under_the_budget(client, monkeypatch):
    resp = _Resp(body=json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode())
    start = time.monotonic()
    _post(client, monkeypatch, resp)
    assert time.monotonic() - start < 1
