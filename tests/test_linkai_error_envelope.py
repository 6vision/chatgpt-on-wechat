"""A rejected LinkAI call has an envelope of its own, and it is not OpenAI's.

LinkAI reports a refusal in more than one shape. ``_handle_linkai_sync_response``
reads the body as ``error_data.get("error", {}).get("message", res.text)`` -- a
default for the missing ``error`` key *and* a fallback to the raw text -- and
``_explain_linkai_error`` names FastAPI's bare ``{"detail": "Not Found"}`` as the
body a misconfigured base produces. So the body may be ``{"error": {...}}``,
``{"message": ...}``, ``{"detail": ...}``, or not JSON at all (a proxy's HTML
502).

``_chat`` and ``reply_text`` are the two methods that spelled the error branch out
by hand, and both wrote it against the OpenAI shape only:

    response = res.json()
    error = response.get("error")
    logger.error(f"... msg={error.get('message')}, type={error.get('type')}")

When the body carries no ``error`` key, ``error`` is ``None`` and
``error.get("message")`` raises ``AttributeError``. That lands in the method's own
``except Exception``, which sleeps two seconds and re-runs the request that was
just refused -- up to its retry bound -- before answering 请再问我一次吧. An HTML
error page raises on ``res.json()`` and takes the same path. The 429/409 wording
the branch was written to produce is unreachable for every shape but OpenAI's.

Both now read the body through ``_linkai_error_body``, the same defensive read
``_handle_linkai_sync_response`` already used.
"""

from unittest.mock import Mock, patch

from bridge.context import Context, ContextType

CONF = {
    "linkai_api_base": "https://api.example.test",
    "linkai_api_key": "test-key",
    "linkai_app_code": "app-1",
    "model": "gpt-4o",
    "temperature": 0.7,
    "top_p": 1,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "channel_type": "web",
}

# LinkAI's own refusal: a code, and the message that explains it.
_BUSINESS_REJECTION = {"code": 40001, "message": "余额不足"}
# What a misconfigured linkai_api_base gets back instead of a route.
_FASTAPI_NOT_FOUND = {"detail": "Not Found"}


class _Sessions:
    def session_msg_query(self, query, session_id):
        return [{"role": "user", "content": query}]


def _bot():
    from models.linkai.link_ai_bot import LinkAIBot

    bot = LinkAIBot.__new__(LinkAIBot)
    bot.sessions = _Sessions()
    bot.args = {}
    return bot


def _chat_context():
    return Context(ContextType.TEXT, "hi", {"session_id": "u1"})


class _Poster:
    """Answer every request with one canned response, and count the requests."""

    def __init__(self, response):
        self.response = response
        self.calls = 0

    def __call__(self, url, **kwargs):
        self.calls += 1
        return self.response


def test_a_rejected_chat_reports_the_message_the_api_sent():
    """A 400 whose body is LinkAI's own ``{"code", "message"}``, not OpenAI's."""
    from models.linkai import link_ai_bot

    response = Mock(status_code=400)
    response.json.return_value = dict(_BUSINESS_REJECTION)
    poster = _Poster(response)

    with patch.object(link_ai_bot, "conf", lambda: dict(CONF)), \
            patch.object(link_ai_bot.requests, "post", poster), \
            patch.object(link_ai_bot.time, "sleep", lambda _s: None):
        reply = _bot()._chat("hi", _chat_context())

    assert poster.calls == 1, "a 400 is a refusal, not something to retry"
    assert reply.content == "提问太快啦，请休息一下再问我吧"


def test_a_rejected_reply_text_reports_the_message_the_api_sent():
    """The same branch, reached through the completion path."""
    from models.linkai import link_ai_bot

    response = Mock(status_code=400)
    response.json.return_value = dict(_FASTAPI_NOT_FOUND)
    poster = _Poster(response)
    session = Mock(messages=[{"role": "user", "content": "hi"}], session_id="u1")

    with patch.object(link_ai_bot, "conf", lambda: dict(CONF)), \
            patch.object(link_ai_bot.requests, "post", poster), \
            patch.object(link_ai_bot.time, "sleep", lambda _s: None):
        result = _bot().reply_text(session)

    assert poster.calls == 1, "a 404 is a refusal, not something to retry"
    assert result["content"] == "提问太快啦，请休息一下再问我吧"


def test_a_proxy_html_error_page_still_retries():
    """Control: a 5xx is retried, and the retry bound is unchanged."""
    from models.linkai import link_ai_bot

    response = Mock(status_code=502, text="<html>Bad Gateway</html>")
    response.json.side_effect = ValueError("No JSON object could be decoded")
    poster = _Poster(response)

    with patch.object(link_ai_bot, "conf", lambda: dict(CONF)), \
            patch.object(link_ai_bot.requests, "post", poster), \
            patch.object(link_ai_bot.time, "sleep", lambda _s: None):
        reply = _bot()._chat("hi", _chat_context())

    assert poster.calls == 3
    assert reply.content == "请再问我一次吧"
