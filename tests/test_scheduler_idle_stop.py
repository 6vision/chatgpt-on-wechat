"""SchedulerService.stop ends the idle worker and a restart never revives an old one."""

import threading
from datetime import datetime

from agent.tools.scheduler.scheduler_service import SchedulerService
from agent.tools.scheduler.task_store import TaskStore


def _store(tmp_path):
    store = TaskStore(str(tmp_path / "tasks.json"))
    store.add_task({"id": "due", "name": "idle-stop task", "enabled": True,
                    "schedule": {"type": "interval", "seconds": 300},
                    "next_run_at": datetime.now().isoformat()})
    return store


def test_stop_and_restart_use_only_a_new_idle_worker(tmp_path):
    ticked, store = threading.Event(), _store(tmp_path)
    service = SchedulerService(store, lambda task: ticked.set())
    service.start()
    first = service.thread
    try:
        assert ticked.wait(3)
        service.start()
        assert service.thread is first
        service.stop()
        assert not first.is_alive()
        ticked.clear()
        store.update_task("due", {"next_run_at": datetime.now().isoformat()})
        service.start()
        assert ticked.wait(3)
        assert service.thread is not first and service.thread.is_alive()
    finally:
        service.stop()
        first.join(timeout=31)


def test_stopped_inflight_worker_cannot_revive_on_restart(tmp_path):
    entered, release = threading.Event(), threading.Event()
    service = SchedulerService(_store(tmp_path), lambda task: entered.set() or release.wait(15))
    service.start()
    old = service.thread
    try:
        assert entered.wait(3)
        service.stop()
        assert old.is_alive(), "stop must not interrupt an in-flight callback"
        service.start()
        assert service.thread is not old
        release.set()
        old.join(timeout=3)
        assert not old.is_alive()
        assert service.running and service.thread.is_alive()
    finally:
        release.set()
        service.stop()
        old.join(timeout=31)
