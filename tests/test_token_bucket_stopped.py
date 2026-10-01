"""Stopped rate limiters must never strand callers waiting for a token."""

import subprocess
import sys
import threading

from common.token_bucket import TokenBucket


def test_disabled_bucket_refuses_without_waiting_forever():
    # The real bot constructors omit timeout, including for fractional rates.
    result = subprocess.run(
        [sys.executable, "-c", (
            "from common.token_bucket import TokenBucket; "
            "bucket = TokenBucket(0.5); "
            "assert bucket.get_token() is False"
        )],
        capture_output=True, text=True, timeout=2,
    )
    assert result.returncode == 0, result.stderr


def test_close_wakes_all_waiting_callers():
    bucket = TokenBucket(1, timeout=4)
    workers = []
    results = []
    try:
        assert bucket.get_token() is True
        for _ in range(3):
            worker = threading.Thread(target=lambda: results.append(bucket.get_token()))
            workers.append(worker)
            worker.start()
        bucket.close()
        for worker in workers:
            worker.join(timeout=0.2)
        assert results == [False, False, False]
        assert bucket.get_token() is False
    finally:
        bucket.close()
        for worker in workers:
            worker.join(timeout=5)
