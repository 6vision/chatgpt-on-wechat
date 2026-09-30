# encoding:utf-8
"""DingTalk answers HTTP 200 with a non-zero ``errcode`` when it rejects a send.

``send_group_message`` parses the body into ``result`` and then ignored it, and
``_send_file_message`` never parsed it at all, so both reported success for a
message that was never delivered: the log said "sent successfully" while the
``if not success:`` fallbacks in ``send()`` stayed dead. The sibling
``send_single_message`` already checks the body, and this file's own
``_reply_markdown_or_text`` documents the contract in a docstring.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock


def _channel():
    """A bare channel whose token and robot code need no network or config."""
    from channel.dingtalk.dingtalk_channel import DingTalkChanel

    cls = DingTalkChanel.__wrapped__
    ch = cls.__new__(cls)
    ch.dingtalk_robot_code = "code"
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


def test_group_send_reports_a_rejected_errcode_as_failure(monkeypatch):
    """A 200 carrying a non-zero errcode means the group never got the text."""
    _post_returning(monkeypatch, REJECTION)

    assert _channel().send_group_message("cid", "hello", "code") is False


def test_group_send_still_reports_a_real_success(monkeypatch):
    """errcode 0 is the acknowledgement, so the send must not be called a failure."""
    _post_returning(monkeypatch, {"errcode": 0, "errmsg": "ok"})

    assert _channel().send_group_message("cid", "hello", "code") is True


def test_file_send_reports_a_rejected_errcode_as_failure(monkeypatch):
    """The file/video/voice path is reached from three branches in send().

    Each of them answers the user with a "发送失败" text when this returns
    False, so returning True on a rejection silently drops the attachment.
    """
    _post_returning(monkeypatch, REJECTION)

    sent = _channel()._send_file_message(
        "tok", _incoming_message(), "sampleFile", {"mediaId": "m"}, True
    )

    assert sent is False


def test_file_send_still_reports_a_real_success(monkeypatch):
    _post_returning(monkeypatch, {"errcode": 0, "errmsg": "ok"})

    sent = _channel()._send_file_message(
        "tok", _incoming_message(), "sampleFile", {"mediaId": "m"}, True
    )

    assert sent is True
