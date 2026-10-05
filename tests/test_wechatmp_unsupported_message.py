"""An unsupported WeChat MP message must be identifiable in the log.

The SDK hands these callbacks more than text / voice / image: a shared link, a
location, a video clip, a mini-program page. The message class parses three of
them and raises `NotImplementedError` for the rest, so the callbacks have to
filter before constructing -- and the log line they used (`暂且不处理`, "not
handled for now") named neither the type nor the sender, which leaves no way to
tell an unsupported message from a mis-parsed one.

`FeishuMessage` already declares the set it can parse as `SUPPORTED_TYPES` and
`feishu_channel.py:774` gates on exactly that, so the two lists cannot drift.
"""
import unittest
from unittest.mock import patch

from wechatpy import parse_message

from channel.wechatmp import active_reply, passive_reply
from channel.wechatmp.wechatmp_message import WeChatMPMessage


def _xml(msg_type: str) -> bytes:
    bodies = {
        "text": "<Content><![CDATA[hello]]></Content>",
        "link": (
            "<Link><Title><![CDATA[t]]></Title>"
            "<Description><![CDATA[d]]></Description>"
            "<Url><![CDATA[https://example.test]]></Url></Link>"
        ),
        "location": (
            "<Location><Location_X>31.2</Location_X><Location_Y>121.5</Location_Y>"
            "<Scale>16</Scale><Label><![CDATA[here]]></Label></Location>"
        ),
    }
    return (
        "<xml><ToUserName><![CDATA[gh]]></ToUserName>"
        "<FromUserName><![CDATA[oUser123]]></FromUserName>"
        f"<CreateTime>1700000000</CreateTime><MsgType><![CDATA[{msg_type}]]></MsgType>"
        f"{bodies[msg_type]}</xml>"
    ).encode("utf-8")


class UnsupportedWechatMPMessageTest(unittest.TestCase):
    def _post(self, module, msg_type):
        """Run the real handler over `msg_type` and return (body, log records)."""
        records = []
        with patch.object(module.web, "input", return_value={}), \
             patch.object(module.web, "data", return_value=_xml(msg_type)), \
             patch.object(module.web, "header"), \
             patch.object(module, "verify_server", return_value=None), \
             patch.object(module.logger, "info",
                          side_effect=lambda m, *a: records.append(str(m))), \
             patch.object(module.logger, "debug"), \
             patch.object(module, "WechatMPChannel") as chan:
            chan.return_value.crypto = None
            body = module.Query().POST()
        return body, records

    def test_the_supported_set_is_declared_not_repeated(self):
        # The constructor handles exactly these three; everything else raises.
        self.assertEqual(WeChatMPMessage.SUPPORTED_TYPES, ("text", "voice", "image"))
        self.assertNotIn("link", WeChatMPMessage.SUPPORTED_TYPES)
        # And the class docstring/comment says what happens otherwise.
        with self.assertRaises(NotImplementedError):
            WeChatMPMessage(parse_message(_xml("link")))

    def test_an_unsupported_type_is_still_answered_success(self):
        # The platform must not retry: "success" is how it is told the message
        # was consumed. This is unchanged -- it is the only thing it can say.
        for module in (passive_reply, active_reply):
            body, _ = self._post(module, "link")
            self.assertEqual(body, "success")

    def test_the_log_names_the_type_and_the_sender(self):
        for module in (passive_reply, active_reply):
            _, records = self._post(module, "link")
            joined = "\n".join(records)
            self.assertIn(
                "link", joined,
                f"{module.__name__} logged {records!r} without naming the type",
            )
            self.assertIn(
                "oUser123", joined,
                f"{module.__name__} logged {records!r} without naming the sender",
            )

    def test_a_location_is_reported_too(self):
        _, records = self._post(passive_reply, "location")
        self.assertIn("location", "\n".join(records))

    def test_a_supported_type_is_not_logged_as_unsupported(self):
        # The control: text still goes to the agent, so nothing is logged.
        for module in (passive_reply, active_reply):
            _, records = self._post(module, "text")
            self.assertNotIn(
                "unsupported message type", "\n".join(records),
                "a text message was reported as unsupported",
            )


if __name__ == "__main__":
    unittest.main()
