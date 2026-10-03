"""A LinkAI API can answer HTTP 200 and still mean "rejected".

LinkAI reports a refused call -- out of credits, a blocked prompt, a bad
parameter -- with HTTP 200 and a non-zero ``code`` in the body, so the status
alone never says whether the call was accepted. That is the envelope every call
site here reads twice (``if res.status_code == 200`` and then
``if res.get("code") == 200``), but the two plugins that talk to it each parsed
it their own way and each got one branch wrong:

- ``MJBot.generate`` and ``MJBot.do_operate`` only returned inside
  ``if code == 200``. A non-zero code fell off the end of the method, so
  ``process_mj_task`` stored ``None`` in ``e_context['reply']`` and a ``$mj`` on
  a refused call produced no message at all -- where a non-200 HTTP status does
  answer with ``图片生成失败``.
- ``LinkSummary``'s error branches called ``res.json()`` unguarded. The body of
  an error page is not JSON (a gateway's HTML 502, say), so reporting a failure
  raised ``ValueError`` out of ``summary_url`` / ``summary_file``.

Both now go through ``Util.parse_linkai_response``, which applies the same
"status and body" rule in one place and always hands back a dict for ``data``.
"""

from unittest.mock import Mock, patch

import plugins
from bridge.context import Context, ContextType
from bridge.reply import ReplyType

# plugins/linkai/__init__.py also imports the registered plugin, which refuses to
# load without a plugin path -- same idiom as test_linkai_summary_file.py.
plugins.instance.current_plugin_path = "./plugins/linkai"
import plugins.linkai.midjourney as midjourney  # noqa: E402
import plugins.linkai.summary as summary_module  # noqa: E402
plugins.instance.current_plugin_path = None

LinkSummary = summary_module.LinkSummary

CONF = {
    "linkai_api_base": "https://api.example.test",
    "linkai_api_key": "test-key",
    "linkai_app_code": "",
    "plugin_trigger_prefix": "$",
}
CONFIG = {"enabled": True, "max_tasks": 5, "max_tasks_per_user": 3}

# What LinkAI sends when it refuses: HTTP 200, a non-zero code, a message.
_BUSINESS_REJECTION = {"code": 40001, "message": "余额不足"}


def _rejected(status_code=200, body=None):
    response = Mock(status_code=status_code)
    response.json.return_value = dict(_BUSINESS_REJECTION) if body is None else body
    return response


def _bot():
    return midjourney.MJBot(CONFIG, fetch_group_app_code=lambda _: None)


def _context():
    context = Context(ContextType.TEXT, "$mj a cat")
    context["session_id"] = "u1"
    return context


def test_a_non_200_business_code_still_answers_the_user():
    with patch.object(midjourney, "conf", lambda: CONF), \
            patch.object(midjourney.requests, "post", return_value=_rejected()):
        reply = _bot().generate("a cat", "u1", _context())

    assert reply is not None, "a refused generate left the user with no answer"
    assert reply.type is ReplyType.ERROR


def test_a_non_200_business_code_answers_on_operate():
    with patch.object(midjourney, "conf", lambda: CONF), \
            patch.object(midjourney.requests, "post", return_value=_rejected()):
        reply = _bot().do_operate(midjourney.TaskType.UPSCALE, "u1", "img-1", _context(), 1)

    assert reply is not None, "a refused operate left the user with no answer"
    assert reply.type is ReplyType.ERROR


def test_a_non_json_error_body_does_not_raise():
    """A 5xx from a proxy is an HTML page, not the JSON envelope."""
    response = Mock(status_code=502)
    response.json.side_effect = ValueError("No JSON object could be decoded")

    assert LinkSummary()._parse_summary_res(response) is None


def test_a_200_with_a_good_code_is_still_accepted():
    """Control: not every 200 may turn into a rejection."""
    response = Mock(status_code=200)
    response.json.return_value = {"code": 200, "data": {"summary": "s", "summary_id": "id-1"}}

    assert LinkSummary()._parse_summary_res(response) == {"summary": "s", "summary_id": "id-1"}
