"""A superseded Feishu register worker must not write into the new session."""

import threading
import time
import unittest
from unittest.mock import patch

from channel.web.api.channels import FeishuRegisterHandler as H


class FeishuRegisterSessionOwnershipTest(unittest.TestCase):
    def setUp(self):
        H._reset_state()
        self.addCleanup(H._reset_state)

        # The worker runs on its own thread, so the patches live for the test.
        from channel.feishu import lark_install

        for p in (
            patch.object(lark_install, "needs_download", return_value=False),
            patch.object(lark_install, "ensure", lambda allow_install=True: None),
            patch("lark_oapi.register_app", side_effect=self._register_app),
        ):
            p.start()
            self.addCleanup(p.stop)

        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.result = {}

    def _register_app(self, on_qr_code=None, on_status_change=None, source=None,
                      cancel_event=None, **kwargs):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("the test never released register_app")
        if on_qr_code is not None:
            on_qr_code({"url": "https://example.test/qr", "expire_in": 600})
        return dict(self.result)

    def _start_worker(self):
        self.entered.clear()
        t = threading.Thread(target=H._start_register_thread, daemon=True)
        t.start()
        self.assertTrue(self.entered.wait(timeout=5),
                        "the worker never reached register_app")
        return t

    def _release_and_join(self, t, predicate):
        self.release.set()
        t.join(timeout=5)
        self.assertFalse(t.is_alive(), "the worker never finished")
        deadline = time.time() + 5
        while time.time() < deadline and not predicate():
            time.sleep(0.02)
        return predicate()

    def _supersede(self):
        with H._lock:
            H._state["cancel_event"].set()
            H._state = {"status": "starting", "cancel_event": threading.Event()}

    def test_a_superseded_worker_does_not_hand_over_its_credentials(self):
        self.release.clear()
        self.result = {
            "client_id": "APP_OF_THE_DEAD",
            "client_secret": "SECRET_OF_THE_DEAD",
        }
        t = self._start_worker()

        self._supersede()
        with H._lock:
            H._state["app_id"] = "APP_OF_THE_LIVE"
            H._state["url"] = "https://example.test/live-qr"

        self._release_and_join(t, lambda: H._state.get("url") == "https://example.test/live-qr"
                              or H._state.get("status") != "pending")

        with H._lock:
            self.assertEqual(H._state["app_id"], "APP_OF_THE_LIVE")
            self.assertNotEqual(H._state.get("status"), "done")
            self.assertEqual(H._state["url"], "https://example.test/live-qr")

    def test_the_owning_worker_still_records_everything(self):
        self.result = {"client_id": "APP_OK", "client_secret": "SECRET_OK"}
        t = self._start_worker()
        self._release_and_join(t, lambda: H._state.get("status") == "done")

        with H._lock:
            self.assertEqual(H._state["status"], "done")
            self.assertEqual(H._state["app_id"], "APP_OK")
            self.assertEqual(H._state["app_secret"], "SECRET_OK")
            self.assertEqual(H._state["url"], "https://example.test/qr")


if __name__ == "__main__":
    unittest.main()
