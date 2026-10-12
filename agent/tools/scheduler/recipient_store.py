"""Persistent directory of trusted scheduler delivery targets."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional


class RecipientStore:
    """Remember recipient identities learned from accepted inbound messages.

    The store deliberately contains no access tokens or channel credentials.
    Channel implementations remain responsible for authentication and their
    normal outbound readiness checks.

    The directory is shared across Agents, but keyed by ``(instance_id, receiver)``
    rather than by ``(channel_type, receiver)``. A channel *type* can run several
    *instances* (two Feishu bots, two WeChat logins), each with its own login,
    tokens and — crucially — its own id space for receivers: the same receiver
    string on two WeChat instances is two different people. Delivery therefore has
    to go back out through the exact instance that first saw the contact, so the
    instance is part of the identity, not just the type.

    Legacy single-instance installs use ``instance_id == channel_type`` (that is
    how the launcher already synthesizes them), so an old entry saved under just a
    channel type keeps resolving unchanged.

    The owning Agent of a scheduled delivery is derived from the recipient's
    channel instance (an instance binds to one Agent), so it is not stored here.
    """

    def __init__(self, store_path: str) -> None:
        self.store_path = Path(store_path)
        self._lock = threading.RLock()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(instance_id: str, receiver: str) -> str:
        # Escape the delimiter and the escape marker in each component. Plain
        # identities retain their existing readable keys; embedded colons cannot
        # make two different instance/receiver pairs alias the same contact.
        def escape(component: str) -> str:
            return component.replace("%", "%25").replace(":", "%3A")

        return f"{escape(instance_id)}:{escape(receiver)}"

    def _load_unlocked(self) -> Dict[str, dict]:
        if not self.store_path.exists():
            return {}
        try:
            with self.store_path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            recipients = value.get("recipients", {})
            if not isinstance(recipients, dict):
                return {}
            # Legacy keys joined unescaped components. Rebuild from the stored
            # structured identity, so an ambiguous old key never routes a lookup
            # to another instance. Persist the normalized keys on the next save.
            normalized = {}
            for key, entry in recipients.items():
                if isinstance(entry, dict):
                    identity = self._normalize(entry)
                    instance_id = identity.get("instance_id")
                    receiver = identity.get("receiver")
                    if isinstance(instance_id, str) and isinstance(receiver, str):
                        key = self._key(instance_id, receiver)
                normalized[key] = entry
            return normalized
        except (OSError, ValueError, TypeError):
            return {}

    def _save_unlocked(self, recipients: Dict[str, dict]) -> None:
        payload = {"version": 1, "recipients": recipients}
        temporary = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.store_path)

    @staticmethod
    def _normalize(entry: dict) -> dict:
        """Fill fields an older on-disk entry may predate, without rewriting it.

        ``instance_id`` predates multi-instance and defaults to the channel type,
        which is exactly the legacy single-instance id, so an old entry resolves
        and delivers the same as before.
        """
        result = dict(entry)
        if not result.get("instance_id"):
            result["instance_id"] = result.get("channel_type", "")
        return result

    def remember(
        self,
        channel_type: str,
        receiver: str,
        *,
        name: str = "",
        is_group: bool = False,
        session_id: str = "",
        instance_id: str = "",
    ) -> Optional[dict]:
        channel_type = str(channel_type or "").strip()
        receiver = str(receiver or "").strip()
        # A missing instance_id means a legacy single-instance channel, whose id
        # is the channel type; this keeps old callers and old data on one path.
        instance_id = str(instance_id or "").strip() or channel_type
        if not channel_type or not receiver or channel_type in {"unknown", "web"}:
            return None
        entry = {
            "channel_type": channel_type,
            "instance_id": instance_id,
            "receiver": receiver,
            "name": str(name or receiver),
            "is_group": bool(is_group),
            "session_id": str(session_id or receiver),
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            recipients = self._load_unlocked()
            key = self._key(instance_id, receiver)
            previous = recipients.get(key)
            if previous:
                stable_fields = (
                    "channel_type",
                    "instance_id",
                    "receiver",
                    "name",
                    "is_group",
                    "session_id",
                )
                unchanged = all(previous.get(field) == entry[field] for field in stable_fields)
                if unchanged:
                    try:
                        last_seen = datetime.fromisoformat(previous["last_seen_at"])
                        if datetime.now(timezone.utc) - last_seen < timedelta(hours=1):
                            return dict(previous)
                    except (KeyError, TypeError, ValueError):
                        pass
            recipients[key] = entry
            self._save_unlocked(recipients)
        return dict(entry)

    def get(self, instance_id: str, receiver: str) -> Optional[dict]:
        """Resolve one recipient by the instance that saw them.

        ``instance_id`` may be a legacy channel type, which is the id a
        single-instance channel runs under, so old lookups keep working.
        """
        instance_id = str(instance_id or "").strip()
        with self._lock:
            entry = self._load_unlocked().get(self._key(instance_id, receiver))
        return self._normalize(entry) if entry else None

    def list(self) -> List[dict]:
        with self._lock:
            entries = [self._normalize(item) for item in self._load_unlocked().values()]
        return sorted(
            entries,
            key=lambda item: (item["channel_type"], item["name"], item["receiver"]),
        )
