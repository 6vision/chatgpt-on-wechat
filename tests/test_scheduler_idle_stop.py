"""Native persisted scheduler lifecycle controls, without channel delivery."""

import threading
from datetime import datetime

from agent.tools.scheduler.scheduler_service import SchedulerService
from agent.tools.scheduler.task_store import TaskStore


def _store(tmp_path):
    store = TaskStore(str(tmp_path / "tasks.json"))
    store.add_task({
        "id": "due", "name": "owned idle-stop task", "enabled": True,
        "schedule": {"type": "interval", "seconds": 300},
        "next_run_at": datetime.now().isoformat(),
    })
    return store


def test_stop_ends_idle_native_scheduler_thread(tmp_path):
    ticked = threading.Event()
    service = SchedulerService(_store(tmp_path), lambda task: ticked.set())
    original = None
    try:
        service.start()
        original = service.thread
        assert ticked.wait(3), "real scheduler loop did not execute its due task"
        service.stop()
        assert not original.is_alive(), "stop returned while the idle timer remains alive"
    finally:
        service.stop()
        if original is not None:
            original.join(timeout=31)


def test_restart_uses_only_new_idle_worker(tmp_path):
    ticked = threading.Event()
    store = _store(tmp_path)
    service = SchedulerService(store, lambda task: ticked.set())
    workers = []
    try:
        service.start()
        workers.append(service.thread)
        assert ticked.wait(3)
        service.start()
        assert service.thread is workers[0]
        service.stop()
        ticked.clear()
        store.update_task("due", {"next_run_at": datetime.now().isoformat()})
        service.start()
        workers.append(service.thread)
        assert ticked.wait(3)
        assert workers[1] is not workers[0]
        assert not workers[0].is_alive()
        assert workers[1].is_alive()
    finally:
        service.stop()
        for worker in workers:
            worker.join(timeout=31)


def test_stopped_inflight_worker_cannot_revive_on_restart(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def execute(task):
        entered.set()
        assert release.wait(15), "owned callback was not released"
        return True

    service = SchedulerService(_store(tmp_path), execute)
    old = None
    try:
        service.start()
        old = service.thread
        assert entered.wait(3)
        service.stop()
        assert old.is_alive(), "stop must retain the existing in-flight callback policy"
        service.start()
        assert service.thread is not old
        release.set()
        old.join(timeout=3)
        assert not old.is_alive(), "an old generation resumed after restart"
        assert service.running and service.thread.is_alive()
    finally:
        release.set()
        service.stop()
        if old is not None:
            old.join(timeout=31)
