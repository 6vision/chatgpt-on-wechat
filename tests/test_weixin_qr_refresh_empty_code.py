"""A QR refresh that returns no code ends the login instead of polling nothing."""

from unittest.mock import patch

from channel.weixin import weixin_channel as wx

WITH_QRCODE = {"qrcode": "QR_abc", "qrcode_img_content": "https://x/y.png"}
NO_QRCODE = {"errcode": 40001, "errmsg": "rate limited"}


class _Stop:
    def is_set(self):
        return False

    def wait(self, _timeout=None):
        return False


class _Api:
    def __init__(self, fetches):
        self.fetches = list(fetches)
        self.polled = []

    def fetch_qr_code(self):
        return dict(self.fetches.pop(0) if len(self.fetches) > 1 else self.fetches[0])

    def poll_qr_status(self, qrcode, timeout=None):
        self.polled.append(qrcode)
        return {"status": "expired"}


def _login(fetches, max_refreshes=3):
    cls = wx.WeixinChannel.__wrapped__
    ch = cls.__new__(cls)
    ch._stop_event = _Stop()
    ch._current_qr_url = ""
    ch._credentials_path = "creds.json"
    api, printed = _Api(fetches), []
    with patch.object(wx, "WeixinApi", return_value=api), \
            patch.object(wx, "QR_MAX_REFRESHES", max_refreshes), \
            patch.object(ch, "_print_qr", printed.append), \
            patch.object(ch, "_notify_cloud_qrcode", lambda url: None), \
            patch("builtins.print", lambda *a, **k: None):
        result = ch._qr_login(base_url="https://example.test")
    return result, api, printed, ch


def test_empty_refresh_ends_the_login():
    result, api, printed, ch = _login([WITH_QRCODE, NO_QRCODE])
    assert result == {}
    assert api.polled == ["QR_abc"]
    assert printed == ["https://x/y.png"]
    assert ch._current_qr_url == ""


def test_healthy_refresh_is_polled():
    new = {"qrcode": "QR_new", "qrcode_img_content": "https://x/new.png"}
    _result, api, printed, _ch = _login([WITH_QRCODE, new], max_refreshes=5)
    assert "QR_new" in api.polled and "https://x/new.png" in printed
