"""A transport failure must never be reported as a delivered message.

``_post`` used to answer *any* timeout with a synthetic ``{"ret": 0, "msgs": []}``.
Every caller reads ``ret`` to decide whether anything went wrong, so a
``sendMessage`` whose response never arrived looked like a successful delivery.

The two kinds of timeout mean different things and are handled apart:

* a ``ConnectTimeout`` -- like an ``SSLError`` or a ``ConnectionError`` -- means
  the request never reached the peer, so nothing was delivered: it is safe to
  retry, and the failure is raised once the retries run out;
* a ``ReadTimeout`` means the request *did* reach the peer and only the response
  was lost, so retrying a send could deliver the same message twice. It is
  therefore raised right away, without a retry.

``get_updates`` is the one caller that reads a timeout differently: it is a long
poll, so a read timeout simply means no message arrived within the window. It
stays an empty poll (logged at debug level, as before) instead of an error --
retrying there is pointless because the next iteration *is* the retry.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from channel.weixin import weixin_api


def _api() -> "weixin_api.WeixinApi":
    return weixin_api.WeixinApi(base_url="https://example.invalid/", token="token")


def _ok_response(payload):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


def _send(api, error):
    """Send a message while ``requests.post`` keeps failing with *error*.

    Returns ``(outcome, attempts)``: the exception that came out (or the value
    returned if the call swallowed the failure) and how many requests were made.
    """
    attempts = []

    def fake_post(*args, **kwargs):
        attempts.append(1)
        raise error

    with patch.object(weixin_api.requests, "post", side_effect=fake_post), \
            patch.object(weixin_api, "time", MagicMock()):
        try:
            outcome = api.send_text("user-1", "hello", "context-token")
        except Exception as raised:
            outcome = raised
    return outcome, attempts


def test_a_read_timeout_is_raised_instead_of_answering_with_a_fake_success():
    api = _api()
    outcome, _ = _send(api, requests.exceptions.ReadTimeout("Read timed out."))

    assert not isinstance(outcome, dict), (
        "a send whose response never arrived must not answer with a synthetic ret=0"
    )
    assert isinstance(outcome, requests.exceptions.ReadTimeout)


def test_a_read_timeout_is_not_retried():
    api = _api()
    outcome, attempts = _send(api, requests.exceptions.ReadTimeout("Read timed out."))

    assert isinstance(outcome, requests.exceptions.ReadTimeout), (
        "a read timeout must surface, not be swallowed into a synthetic response"
    )
    assert len(attempts) == 1, (
        "the request already reached the peer, so retrying could deliver it twice"
    )


def test_a_connect_timeout_is_retried_before_it_is_raised():
    api = _api()
    outcome, attempts = _send(api, requests.exceptions.ConnectTimeout("connect timed out"))

    assert isinstance(outcome, requests.exceptions.ConnectTimeout)
    assert len(attempts) == weixin_api.SEND_RETRIES + 1


def test_a_dropped_connection_is_retried_before_it_is_raised():
    api = _api()
    outcome, attempts = _send(api, requests.exceptions.ConnectionError("peer reset"))

    assert isinstance(outcome, requests.exceptions.ConnectionError)
    assert len(attempts) == weixin_api.SEND_RETRIES + 1


def test_a_read_timeout_on_the_long_poll_is_an_empty_poll():
    api = _api()
    with patch.object(weixin_api.requests, "post",
                      side_effect=requests.exceptions.ReadTimeout("Read timed out.")):
        assert api.get_updates("cursor") == {"ret": 0, "msgs": []}


def test_a_connect_failure_on_the_long_poll_is_still_raised():
    api = _api()
    with patch.object(weixin_api.requests, "post",
                      side_effect=requests.exceptions.ConnectionError("unreachable")):
        with pytest.raises(requests.exceptions.ConnectionError):
            api.get_updates("cursor")


def test_an_http_error_is_raised_without_being_retried():
    api = _api()
    response = MagicMock()
    response.status_code = 500
    response.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
    attempts = []

    def fake_post(*args, **kwargs):
        attempts.append(1)
        return response

    with patch.object(weixin_api.requests, "post", side_effect=fake_post), \
            patch.object(weixin_api, "time", MagicMock()):
        with pytest.raises(requests.exceptions.HTTPError):
            api.send_text("user-1", "hello", "context-token")

    assert len(attempts) == 1


def test_a_delivered_message_still_returns_its_response():
    api = _api()
    payload = {"ret": 0, "msgs": []}
    with patch.object(weixin_api.requests, "post", return_value=_ok_response(payload)):
        assert api.send_text("user-1", "hello", "context-token") == payload
