"""A superseded Feishu register worker must not write into the new session.

`_start_register_thread` replaces `_state` and sets the previous worker's
`cancel_event`, but the `lark.register_app` call already in flight still
returns and still runs its callbacks. One write site checked that it still
owned the session; the other four did not, so a worker the user had retried away
from could hand the console credentials for the abandoned app.
"""
import threading
import time
import unittest
from unittest.mock import patch

from channel.web.api.channels import FeishuRegisterHandler as H


class FeishuRegisterSessionOwnershipTest(unittest.TestCase):
    """Drives the real worker through _start_register_thread."""

    def setUp(self):
        H._reset_state()
        self.addCleanup(H._reset_state)

        # The worker runs on its own thread, so a `with patch(...)` wrapped
        # around the thread start would be undone before the worker reached
        # register_app. Hold the patches for the whole test instead.
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
        """Stands in for the SDK call, holding the window the bug lives in."""
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("the test never released register_app")
        if on_qr_code is not None:
            on_qr_code({"url": "https://example.test/qr", "expire_in": 600})
        return dict(self.result)

    def _start_worker(self):
        """Start a worker and wait until it is inside register_app."""
        self.entered.clear()
        t = threading.Thread(target=H._start_register_thread, daemon=True)
        t.start()
        self.assertTrue(self.entered.wait(timeout=5),
                        "the worker never reached register_app")
        return t

    def _release_and_join(self, t, predicate):
        """Let the SDK call return, then wait for `predicate` to hold.

        Thread liveness is not enough: the worker can still be inside the
        `with cls._lock` block when join() is called, so the write being waited
        for has not necessarily happened yet.
        """
        self.release.set()
        t.join(timeout=5)
        self.assertFalse(t.is_alive(), "the worker never finished")
        deadline = time.time() + 5
        while time.time() < deadline and not predicate():
            time.sleep(0.02)
        return predicate()

    def _supersede(self):
        """What a retry does: cancel the old worker, install a new session."""
        with H._lock:
            H._state["cancel_event"].set()
            H._state = {"status": "starting", "cancel_event": threading.Event()}

    # -- the predicate ----------------------------------------------------

    def test_owns_session_compares_the_cancel_event(self):
        mine = threading.Event()
        with H._lock:
            H._state = {"status": "starting", "cancel_event": mine}

        self.assertTrue(H._owns_session(mine))

        self._supersede()
        self.assertFalse(
            H._owns_session(mine),
            "a worker whose session was replaced still claims to own the state",
        )

    def test_owns_session_is_false_for_an_unknown_event(self):
        # _reset_state() empties the dict, so .get() is None and any event is a
        # stranger. That must answer False rather than raise.
        with H._lock:
            H._state = {}
        self.assertFalse(H._owns_session(threading.Event()))

    # -- the race ---------------------------------------------------------

    def test_a_superseded_worker_does_not_hand_over_its_credentials(self):
        self.release.clear()
        self.result = {
            "client_id": "APP_OF_THE_DEAD",
            "client_secret": "SECRET_OF_THE_DEAD",
        }
        t = self._start_worker()

        # The user hits retry: new session, old worker cancelled. The live
        # session has meanwhile put its own app and QR in place.
        self._supersede()
        with H._lock:
            H._state["app_id"] = "APP_OF_THE_LIVE"
            H._state["url"] = "https://example.test/live-qr"

        self._release_and_join(t, lambda: H._state.get("url") == "https://example.test/live-qr"
                              or H._state.get("status") != "pending")

        with H._lock:
            self.assertNotEqual(
                H._state.get("app_id"), "APP_OF_THE_DEAD",
                "the cancelled attempt's app was written into the live session",
            )
            self.assertEqual(H._state["app_id"], "APP_OF_THE_LIVE")
            self.assertNotEqual(
                H._state.get("status"), "done",
                "the live session was marked done by somebody else's app",
            )
            self.assertEqual(
                H._state["url"], "https://example.test/live-qr",
                "the stale QR replaced the live session's own",
            )

    def test_a_superseded_worker_does_not_replace_the_live_qr(self):
        self.release.clear()
        t = self._start_worker()
        self._supersede()
        with H._lock:
            H._state["url"] = "https://example.test/live-qr"

        self._release_and_join(t, lambda: H._state.get("status") != "pending")

        with H._lock:
            self.assertEqual(H._state["url"], "https://example.test/live-qr")
            self.assertNotEqual(H._state.get("status"), "pending")

    # -- the control ------------------------------------------------------

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
