import pytest
from common import token_bucket

class Notifications:
    def __init__(self):
        self.now = 0.0
        self.waits = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def wait(self, timeout):
        self.waits.append(timeout)
        if len(self.waits) == 1:
            self.now += 0.4
            return True
        self.now += timeout
        return False

def test_notifications_do_not_restart_the_timeout(monkeypatch):
    condition = Notifications()
    bucket = token_bucket.TokenBucket.__new__(token_bucket.TokenBucket)
    bucket.cond = condition
    bucket.tokens = 0
    bucket.is_running = True
    bucket.timeout = 1.0
    monkeypatch.setattr(token_bucket.time, "monotonic", lambda: condition.now)
    assert bucket.get_token() is False
    assert condition.now == pytest.approx(1.0)
    assert condition.waits == pytest.approx([1.0, 0.6])

def test_zero_timeout_does_not_wait():
    bucket = token_bucket.TokenBucket.__new__(token_bucket.TokenBucket)
    bucket.cond = Notifications()
    bucket.tokens = 0
    bucket.is_running = True
    bucket.timeout = 0
    assert bucket.get_token() is False
    assert bucket.cond.waits == []
