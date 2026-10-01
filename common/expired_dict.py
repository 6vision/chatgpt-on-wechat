from datetime import datetime, timedelta

# Expired entries are swept on write, at most this often (or once per TTL when
# the TTL is shorter), so a sweep stays cheap on busy dedup caches.
_MAX_PURGE_INTERVAL_SECONDS = 60
_MISSING = object()


class ExpiredDict(dict):
    def __init__(self, expires_in_seconds):
        super().__init__()
        self.expires_in_seconds = expires_in_seconds
        self._purge_interval = timedelta(seconds=min(expires_in_seconds, _MAX_PURGE_INTERVAL_SECONDS))
        self._next_purge = datetime.now() + self._purge_interval

    def __getitem__(self, key):
        value, expiry_time = super().__getitem__(key)
        if datetime.now() > expiry_time:
            del self[key]
            raise KeyError("expired {}".format(key))
        self.__setitem__(key, value)
        return value

    def __setitem__(self, key, value):
        now = datetime.now()
        if now >= self._next_purge:
            self._purge_expired(now)
        expiry_time = now + timedelta(seconds=self.expires_in_seconds)
        super().__setitem__(key, (value, expiry_time))

    def _purge_expired(self, now=None):
        """Drop every expired entry, including ones nobody will look up again."""
        now = now or datetime.now()
        self._next_purge = now + self._purge_interval
        for key, (_, expiry_time) in list(super().items()):
            if now > expiry_time:
                super().pop(key, None)

    def _live_items(self):
        """Unexpired (key, value) pairs. Listing them does not extend their TTL."""
        now = datetime.now()
        return [(key, value) for key, (value, expiry_time) in list(super().items()) if now <= expiry_time]

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def pop(self, key, default=_MISSING):
        entry = super().pop(key, _MISSING)
        if entry is _MISSING or datetime.now() > entry[1]:
            if default is _MISSING:
                raise KeyError(key)
            return default
        return entry[0]

    def __contains__(self, key):
        try:
            self[key]
            return True
        except KeyError:
            return False

    def __len__(self):
        self._purge_expired()
        return super().__len__()

    def keys(self):
        return [key for key, _ in self._live_items()]

    def values(self):
        return [value for _, value in self._live_items()]

    def items(self):
        return self._live_items()

    def __iter__(self):
        return iter(self.keys())
