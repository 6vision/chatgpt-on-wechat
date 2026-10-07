"""An unsupported WeChat MP message is acknowledged and logged with its type and sender."""

import unittest
from unittest.mock import patch

from channel.wechatmp import active_reply, passive_reply


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

    def test_unsupported_type_is_acknowledged_and_named(self):
        for module in (passive_reply, active_reply):
            for msg_type in ("link", "location"):
                body, records = self._post(module, msg_type)
                joined = "\n".join(records)
                self.assertEqual(body, "success")
                self.assertIn(msg_type, joined)
                self.assertIn("oUser123", joined)

    def test_a_supported_type_is_not_logged_as_unsupported(self):
        for module in (passive_reply, active_reply):
            _, records = self._post(module, "text")
            self.assertNotIn("unsupported message type", "\n".join(records))


if __name__ == "__main__":
    unittest.main()
