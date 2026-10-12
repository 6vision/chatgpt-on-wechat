"""SSE lines can independently use LF, CR, or CRLF."""
import itertools
import json

import pytest

from models.openai.openai_http_client import OpenAIHTTPClient


class Response:
    def __init__(self, chunks):
        self.chunks = chunks

    def iter_content(self, **kwargs):
        return iter(self.chunks)


@pytest.mark.parametrize("first,second", [pair for pair in itertools.product([b"\n", b"\r", b"\r\n"], repeat=2) if pair != (b"\r", b"\n")])
def test_mixed_line_endings_dispatch_separate_events(first, second):
    stream = b'data: {"part": 1}' + first + second + b'data: {"part": 2}' + first + second
    assert list(OpenAIHTTPClient._iter_sse_events(Response([stream]))) == ['{"part": 1}', '{"part": 2}']


def test_initial_bom_can_span_network_chunks():
    stream = b'\xef\xbb\xbfdata: {"part": 1}\r\n\r\ndata: [DONE]\n\n'
    assert list(OpenAIHTTPClient._iter_sse_events(Response([bytes([byte]) for byte in stream]))) == ['{"part": 1}', '[DONE]']


def test_unicode_separators_inside_json_are_not_sse_newlines():
    payload = json.dumps({"content": "alpha\u2028beta\u0085gamma"}, ensure_ascii=False)
    stream = ('data: ' + payload + '\n\n').encode()
    events = list(OpenAIHTTPClient._iter_sse_events(Response([bytes([byte]) for byte in stream])))
    assert events == [payload]
    assert json.loads(events[0])["content"] == "alpha\u2028beta\u0085gamma"


def test_comments_multiline_data_and_fragmented_crlf():
    stream = b': comment\r\ndata: first\r\ndata:  second\r\n\r\n'
    assert list(OpenAIHTTPClient._iter_sse_events(Response([bytes([byte]) for byte in stream]))) == ['first\n second']


def test_existing_unterminated_proxy_event_remains_supported():
    assert list(OpenAIHTTPClient._iter_sse_events(Response([b'data: [DONE]']))) == ['[DONE]']
