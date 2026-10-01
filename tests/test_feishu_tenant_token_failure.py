"""Regression tests for the Feishu tenant access token request."""

from unittest.mock import patch

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.feishu.feishu_channel import FeiShuChanel

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"


class TokenResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def __repr__(self):
        return f"<Response [{self.status_code}]>"


def _channel():
    # fetch_access_token only reads the two credentials, and the class is wrapped
    # by @singleton, so build a bare instance from the undecorated class instead
    # of starting a channel.
    cls = FeiShuChanel.__wrapped__
    channel = cls.__new__(cls)
    channel.feishu_app_id = "cli_test_app_id"
    channel.feishu_app_secret = "test_app_secret"
    return channel


def _post(response):
    # Records what the caller passed so the test can assert on the timeout.
    def post(url, data=None, headers=None, timeout=None):
        post.calls.append({"url": url, "timeout": timeout})
        return response

    post.calls = []
    return post


def test_non_200_returns_empty_string_instead_of_none():
    post = _post(TokenResponse(503))

    with patch("channel.feishu.feishu_channel.requests.post", side_effect=post):
        token = _channel().fetch_access_token()

    # send() concatenates "Bearer " + token. Falling off the end of the function
    # returned None there, and the resulting TypeError was retried into silence:
    # a scheduled push whose token request 503'd delivered nothing at all.
    assert token == ""
    assert isinstance(token, str)


def test_api_error_code_returns_empty_string():
    # The sibling branch above already had this behaviour; keep both failures
    # reporting themselves the same way.
    post = _post(TokenResponse(200, {"code": 99991663, "msg": "no permission"}))

    with patch("channel.feishu.feishu_channel.requests.post", side_effect=post):
        token = _channel().fetch_access_token()

    assert token == ""
    assert isinstance(token, str)


def test_token_request_is_bounded():
    post = _post(TokenResponse(200, {"code": 0, "tenant_access_token": "t-abc123"}))

    with patch("channel.feishu.feishu_channel.requests.post", side_effect=post):
        token = _channel().fetch_access_token()

    assert token == "t-abc123"
    # Every other requests.* call in this module is bounded; an unbounded token
    # request is the one that can hang a push worker forever.
    assert post.calls[0]["timeout"] == (5, 10)


def test_send_does_not_build_a_bearer_header_without_a_token():
    # A scheduled push has no msg to borrow a token from, so send() asks for a
    # fresh one. When that fails it must bail out rather than concatenate a
    # missing token into an Authorization header.
    channel = _channel()
    context = Context(ContextType.TEXT, "scheduled push", kwargs={})
    context["isgroup"] = False
    post = _post(TokenResponse(503))

    with patch("channel.feishu.feishu_channel.requests.post", side_effect=post):
        channel.send(Reply(ReplyType.TEXT, "nightly report"), context)

    # Only the token request was attempted; nothing was mailed with "Bearer ".
    assert [call["url"] for call in post.calls] == [TOKEN_URL]
