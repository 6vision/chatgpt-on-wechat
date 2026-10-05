"""A QR refresh that returns nothing must end the login, not loop on it.

`_qr_login` fetches a QR code twice. The first fetch checks the field:

    qrcode = qr_resp.get("qrcode", "")
    if not qrcode:
        logger.error("[Weixin] No QR code returned from server")
        return {}

The refresh on expiry had no such check. `fetch_qr_code` only calls
`raise_for_status()`, so a 200 carrying an error body comes back with no
`qrcode` -- and the good one already in hand was overwritten with nothing. The
loop then polled `get_qrcode_status?qrcode=`, which cannot succeed, and
`poll_qr_status` turns a timeout into `{"status": "wait"}`, so an invalid code
is indistinguishable from a slow one. `QR_MAX_REFRESHES` does not bound it: it
counts expiry events, which a dead code never reports.
"""

import unittest
from unittest.mock import patch

from channel.weixin import weixin_channel as wx


class _Stop:
    """Stands in for the login's stop event."""

    def __init__(self):
        self._set = False

    def is_set(self):
        return self._set

    def set(self):
        self._set = True

    def wait(self, _timeout=None):
        return self._set


def _channel():
    # @singleton rebinds the name to get_instance(); the class is on __wrapped__.
    cls = wx.WeixinChannel.__wrapped__
    ch = cls.__new__(cls)
    ch._stop_event = _Stop()
    ch._current_qr_url = ""
    ch._credentials_path = "creds.json"
    return ch


class _Api:
    """fetch_qr_code returns `payload`; poll_qr_status always reports expired."""

    def __init__(self, payload):
        self.payload = payload
        self.polled = []

    def fetch_qr_code(self):
        return dict(self.payload)

    def poll_qr_status(self, qrcode, timeout=None):
        self.polled.append(qrcode)
        # Enough expiries to exhaust QR_MAX_REFRESHES if the code is accepted.
        if len(self.polled) >= 99:
            return {"status": "expired"}
        return {"status": "expired"}


# A 200 that carries an error payload rather than a QR code.
NO_QRCODE = {"errcode": 40001, "errmsg": "rate limited"}
WITH_QRCODE = {"qrcode": "QR_abc", "qrcode_img_content": "https://x/y.png"}


class QrRefreshEmptyCodeTest(unittest.TestCase):
    def _run_refresh(self, payload, max_refreshes=3):
        """Drive _qr_login to the refresh, then return (result, api)."""
        ch = _channel()
        api = _Api(payload)
        # First fetch good, refresh returns `payload`.
        results = [WITH_QRCODE, payload]

        def fetch():
            return dict(results.pop(0)) if results else dict(payload)

        api.fetch_qr_code = fetch
        # QR_MAX_REFRESHES is compared as `refresh_count >= MAX` *before* the
        # refresh runs, so a cap of 1 would break out without ever refreshing.
        printed = []

        with patch.object(wx, "WeixinApi", return_value=api), \
             patch.object(wx, "QR_MAX_REFRESHES", max_refreshes), \
             patch.object(ch, "_print_qr", lambda url: printed.append(url)), \
             patch.object(ch, "_notify_cloud_qrcode", lambda url: None), \
             patch("builtins.print", lambda *a, **k: None):
            result = ch._qr_login(base_url="https://example.test")
        return result, api, printed

    def test_a_refresh_with_no_qrcode_ends_the_login(self):
        result, api, printed = self._run_refresh(NO_QRCODE)

        self.assertEqual(
            result, {},
            "an empty qrcode was accepted, so the loop kept polling a code that "
            "does not exist",
        )
        self.assertEqual(
            api.polled, ["QR_abc"],
            "polled past the refresh: an empty qrcode reached poll_qr_status",
        )
        # The first fetch legitimately shows its own QR; nothing may be shown
        # for the refresh, because there was no code to put behind it.
        self.assertEqual(
            printed, ["https://x/y.png"],
            "a QR with no code behind it was shown to the user",
        )

    def test_the_stale_qr_url_is_cleared(self):
        ch = _channel()
        api = _Api(NO_QRCODE)
        results = [WITH_QRCODE, NO_QRCODE]
        api.fetch_qr_code = lambda: dict(results.pop(0)) if results else dict(NO_QRCODE)

        with patch.object(wx, "WeixinApi", return_value=api), \
             patch.object(wx, "QR_MAX_REFRESHES", 3), \
             patch.object(ch, "_print_qr", lambda url: None), \
             patch.object(ch, "_notify_cloud_qrcode", lambda url: None), \
             patch("builtins.print", lambda *a, **k: None):
            ch._qr_login(base_url="https://example.test")

        self.assertEqual(
            ch._current_qr_url, "",
            "the cloud console would keep offering a QR that cannot be scanned",
        )

    def test_a_healthy_refresh_still_works(self):
        # The control: a refresh that returns a code is used, and the login goes
        # on to poll the new one.
        result, api, printed = self._run_refresh(
            {"qrcode": "QR_new", "qrcode_img_content": "https://x/new.png"},
            max_refreshes=99,
        )

        self.assertIn("QR_new", api.polled,
                      "the refreshed code was not the one polled")
        self.assertIn("https://x/new.png", printed,
                      "the refreshed QR was not shown")

    def test_the_first_fetch_is_still_guarded(self):
        # The guard this one mirrors: an empty first fetch stops immediately.
        ch = _channel()
        api = _Api(NO_QRCODE)

        with patch.object(wx, "WeixinApi", return_value=api), \
             patch("builtins.print", lambda *a, **k: None):
            result = ch._qr_login(base_url="https://example.test")

        self.assertEqual(result, {})
        self.assertEqual(api.polled, [], "an empty first fetch still polled")


if __name__ == "__main__":
    unittest.main()
