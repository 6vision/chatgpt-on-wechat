"""A browser launch that fails must not leave its driver and Chrome behind.

``_launch_browser`` starts the Playwright driver and *then* dispatches to the
mode-specific launcher, so a launcher that throws leaves both handles live on
the service. ``_run_loop``'s failure path returned straight away, skipping the
``_shutdown_browser()`` further down -- the only place ``_playwright.stop()``
and ``_chrome_launcher.close()`` happen.

Nothing else covers it: ``_start_thread``'s timeout calls ``close()``, but
``_ready`` is set on the way out so it never waits; and ``close()`` itself
returns on ``if not self._alive``, which the failure path had just set to
False. The comment above ``close()``'s stuck-thread branch already describes
this exact hazard ("would stay resident for the rest of the process's life"),
so the gap is in the launch that *throws* rather than the one that hangs.

The mode-specific launchers are replaced with recorders here: what matters is
that the handles set before the throw get reclaimed, not how Chrome is spawned.
"""

import queue
import threading
import unittest

from agent.tools.browser.browser_service import BrowserService


class _Recorder:
    """Stands in for the driver / launcher and records whether it was reclaimed."""

    def __init__(self):
        self.stopped = False
        self.closed = False

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class _FakePlaywright:
    def __init__(self, driver):
        self.chromium = self
        self._driver = driver

    def start(self):
        return self._driver

    def connect_over_cdp(self, endpoint):
        raise AssertionError("not reached in this test")


class BrowserLaunchFailureCleanupTest(unittest.TestCase):

    def _service(self, launcher_error):
        """A BrowserService with just the attributes the launch path touches."""
        service = BrowserService.__new__(BrowserService)
        service._lock = threading.RLock()
        service._task_queue = queue.Queue()
        service._ready = threading.Event()
        service._alive = True
        service._thread = None
        service._playwright = None
        service._chrome_launcher = None
        service._browser = None
        service._context = None
        service._page = None
        service._launch_mode = "system-cdp"
        service._needs_restart = False
        service._idle_timer = None
        service._reaped = []
        service._reap_spawned_processes = lambda: None
        service._cancel_idle_timer = lambda: None

        driver = _Recorder()
        launcher = _Recorder()
        service._driver = driver
        service._launcher = launcher

        def launcher_impl(launch_args, viewport):
            # What the real system-cdp launcher does: spawn first, attach
            # second. The attach is what fails.
            service._chrome_launcher = launcher
            raise launcher_error

        service._launch_system_cdp = launcher_impl

        def fake_launch_browser():
            service._playwright = _FakePlaywright(driver).start()
            service._launch_system_cdp([], {"width": 1, "height": 1})

        service._launch_browser = fake_launch_browser
        return service, driver, launcher

    def test_a_failed_launch_reclaims_the_driver_and_the_browser(self):
        service, driver, launcher = self._service(RuntimeError("cdp refused"))

        service._run_loop()

        self.assertTrue(
            driver.stopped,
            "the Playwright driver outlived the failed launch",
        )
        self.assertTrue(
            launcher.closed,
            "the Chrome spawned for the failed launch was never closed",
        )

    @staticmethod
    def _pending_call(service):
        """A request already queued, as _submit would leave it."""
        slot = {"value": None, "error": None, "event": threading.Event()}
        service._task_queue.put((lambda: None, (), {}, slot))
        return slot

    def test_the_caller_is_still_told_the_launch_failed(self):
        service, _, _ = self._service(RuntimeError("cdp refused"))
        slot = self._pending_call(service)

        service._run_loop()

        # The waiting caller must be released with the launch error, and the
        # manager must not be left looking usable.
        self.assertTrue(slot["event"].is_set(),
                        "the waiting request was never completed")
        self.assertIsInstance(slot["error"], RuntimeError)
        self.assertIn("cdp refused", str(slot["error"]))
        self.assertFalse(service._alive)

    def test_a_cleanup_failure_does_not_hide_the_launch_error(self):
        service, driver, _ = self._service(RuntimeError("cdp refused"))

        def exploding_shutdown():
            raise RuntimeError("teardown blew up too")

        service._shutdown_browser = exploding_shutdown
        slot = self._pending_call(service)

        service._run_loop()  # must not raise

        self.assertTrue(slot["event"].is_set(),
                        "the launch error was swallowed by the cleanup error")
        self.assertIn("cdp refused", str(slot["error"]))
        self.assertTrue(service._ready.is_set())

    def test_the_ready_event_is_set_even_when_cleanup_fails(self):
        # A caller blocked in ready.wait() has to be released either way.
        service, _, _ = self._service(RuntimeError("cdp refused"))
        service._shutdown_browser = lambda: (_ for _ in ()).throw(RuntimeError("boom"))

        service._run_loop()

        self.assertTrue(service._ready.is_set())


if __name__ == "__main__":
    unittest.main()