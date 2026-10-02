# encoding:utf-8
"""The two image send paths must read DingTalk's body errcode, not just the status.

DingTalk answers HTTP 200 with a non-zero ``errcode`` when it rejects a send, so
the status alone is not an acknowledgement. ``send_group_message`` and
``_send_file_message`` were fixed for this, but the two image paths stayed on the
status-only check and reported a dropped image as sent. ``send()`` answers the
user with "抱歉，图片发送失败" when ``send_image_with_media_id`` returns False, so
returning True on a rejection silently drops the image — no fallback for the user
and no error line in the log. The sibling ``_upload_media`` and
``_reply_markdown_or_text`` in the same file already read the body.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock


def _channel():
    """A bare channel whose token needs no network or config."""
    from channel.dingtalk.dingtalk_channel import DingTalkChanel

    cls = DingTalkChanel.__wrapped__
    ch = cls.__new__(cls)
    ch.get_access_token = lambda: "tok"
    return ch


def _incoming_message():
    return SimpleNamespace(
        robot_code="code",
        conversation_id="cid",
        sender_staff_id="staff",
    )


def _post_returning(monkeypatch, body):
    """Answer every POST with HTTP 200 and ``body``, the rejection shape."""
    def fake_post(*args, **kwargs):
        response = MagicMock(status_code=200)
        response.json.return_value = body
        response.text = str(body)
        return response

    monkeypatch.setattr("channel.dingtalk.dingtalk_channel.requests.post", fake_post)


REJECTION = {"errcode": 40035, "errmsg": "robot not in group"}


def test_image_with_media_id_reports_a_rejected_errcode_as_failure(monkeypatch):
    """A 200 carrying a non-zero errcode means the image never reached the user."""
    _post_returning(monkeypatch, REJECTION)

    sent = _channel().send_image_with_media_id("tok", "m", _incoming_message(), False)

    assert sent is False


def test_image_with_media_id_still_reports_a_real_success(monkeypatch):
    _post_returning(monkeypatch, {"errcode": 0, "errmsg": "ok"})

    sent = _channel().send_image_with_media_id("tok", "m", _incoming_message(), False)

    assert sent is True


def test_image_message_reports_a_rejected_errcode_as_failure(monkeypatch):
    """The oToMessages/batchSend path parses ``result`` and then ignored it."""
    _post_returning(monkeypatch, REJECTION)

    sent = _channel().send_image_message("staff", "m", False, "code")

    assert sent is False


def test_image_message_still_reports_a_real_success(monkeypatch):
    _post_returning(monkeypatch, {"errcode": 0, "errmsg": "ok"})

    sent = _channel().send_image_message("staff", "m", False, "code")

    assert sent is True
