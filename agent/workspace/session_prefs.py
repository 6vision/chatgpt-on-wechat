"""Per-session runtime preferences: which model answers, what it may change.

Sibling of :mod:`agent.workspace.project_store`, same shape and same key scheme.
A conversation can pin its own model and its own permission mode; anything not
pinned follows the global settings, so an untouched session keeps behaving the
way the instance is configured.

Why a JSON file rather than the sessions table: the web UI mints a session id in
the browser and a row only appears once the first message is persisted. A user
who picks a model before typing must have somewhere to put it, and this store
has no foreign key to satisfy.

Stored under ``<shared_root>/session_prefs.json``::

    {
      "sessions": {
        "default::session_abc": {
          "provider": "claudeAPI",
          "model": "claude-sonnet-5",
          "permission": "workspace-write",
          "ts": 1731999999.0
        }
      }
    }

Every field is optional. Absent means "follow the global setting".
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, Optional

from common.atomic_write import write_json_atomic
from common.log import logger

# ``members`` is the roster of a team conversation: the Agent ids the session's
# owner may hand work to. Here rather than in a table of its own for the same
# reason the model override is — it can be set before the conversation has a
# single message, so there is no row to hang it off yet. An empty roster is
# stored as absent, which is exactly "not a team conversation".
_FIELDS = ("provider", "model", "permission", "members")

_lock = threading.Lock()


def _store_file() -> str:
    from common.state_dir import shared_root

    return str(shared_root() / "session_prefs.json")


def _load() -> Dict:
    path = _store_file()
    if not os.path.isfile(path):
        return {"sessions": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception as e:
        logger.warning(f"[SessionPrefs] Could not read {path}: {e}")
        return {"sessions": {}}
    if not isinstance(data, dict):
        return {"sessions": {}}
    if not isinstance(data.get("sessions"), dict):
        data["sessions"] = {}
    return data


def _save(data: Dict) -> None:
    path = _store_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_json_atomic(path, data, indent=2)
    except Exception as e:
        logger.warning(f"[SessionPrefs] Could not write {path}: {e}")
        raise


def _session_key(session_id: str, agent_id: Optional[str]) -> str:
    """Namespace by agent so identical session ids across Agents don't collide."""
    return f"{agent_id or 'default'}::{session_id}"


def get_prefs(session_id: str, agent_id: Optional[str] = None) -> Dict:
    """Overrides explicitly set for a session (missing keys = follow global)."""
    if not session_id:
        return {}
    with _lock:
        data = _load()
        entry = data["sessions"].get(_session_key(session_id, agent_id))
    if not isinstance(entry, dict):
        return {}
    return {k: entry[k] for k in _FIELDS if entry.get(k)}


def members_index() -> Dict[tuple, list]:
    """Every team conversation's roster, keyed by ``(agent_id, session_id)``.

    Listing conversations needs the roster for a whole page at once, and asking
    per row would re-read and re-parse the file once per conversation. Only
    team conversations appear here, so an empty result means nobody has ever
    invited anybody.
    """
    with _lock:
        data = _load()
    index: Dict[tuple, list] = {}
    for key, entry in data["sessions"].items():
        if not isinstance(entry, dict) or not entry.get("members"):
            continue
        agent_id, _, session_id = str(key).partition("::")
        if session_id:
            index[(agent_id, session_id)] = list(entry["members"])
    return index


def set_prefs(
    session_id: str,
    agent_id: Optional[str] = None,
    **updates,
) -> Dict:
    """Merge overrides for a session; pass ``None`` for a field to clear it.

    Returns the resulting override dict (empty when the session now follows the
    global settings entirely).
    """
    if not session_id:
        raise ValueError("session_id is required")

    key = _session_key(session_id, agent_id)
    with _lock:
        data = _load()
        entry = data["sessions"].get(key)
        entry = dict(entry) if isinstance(entry, dict) else {}

        for field in _FIELDS:
            if field not in updates:
                continue
            value = updates[field]
            if value is None or (isinstance(value, str) and not value.strip()):
                entry.pop(field, None)
            else:
                entry[field] = value.strip() if isinstance(value, str) else value

        result = {k: entry[k] for k in _FIELDS if entry.get(k)}
        if result:
            data["sessions"][key] = {**result, "ts": time.time()}
        else:
            # Nothing pinned any more: drop the row instead of leaving a husk.
            data["sessions"].pop(key, None)
        _save(data)
    return result


def forget_session(session_id: str, agent_id: Optional[str] = None) -> None:
    """Drop a session's overrides (called when the conversation is deleted)."""
    if not session_id:
        return
    key = _session_key(session_id, agent_id)
    with _lock:
        data = _load()
        if data["sessions"].pop(key, None) is not None:
            _save(data)


def forget_agent(agent_id: str) -> None:
    """Erase every trace of a deleted Agent from the prefs store.

    Deleting an Agent leaves two kinds of dangling references here that would
    otherwise linger forever:

    - Its own sessions' overrides, keyed ``{agent_id}::*`` — orphaned, because
      the conversations they belonged to were removed with the Agent's
      workspace.
    - Its id sitting in *other* Agents' team ``members`` rosters — a ghost
      teammate the composer/settings would keep offering as ``available:false``.

    Both are pruned in one pass; a row left with nothing pinned is dropped
    rather than kept as an empty husk.
    """
    if not agent_id:
        return
    owner_prefix = f"{agent_id}::"
    with _lock:
        data = _load()
        sessions = data["sessions"]
        changed = False

        for key in [k for k in sessions if str(k).startswith(owner_prefix)]:
            sessions.pop(key, None)
            changed = True

        for key, entry in list(sessions.items()):
            if not isinstance(entry, dict) or not entry.get("members"):
                continue
            members = [m for m in entry["members"] if m != agent_id]
            if len(members) == len(entry["members"]):
                continue
            changed = True
            if members:
                entry["members"] = members
            else:
                entry.pop("members", None)
                if not any(entry.get(f) for f in _FIELDS):
                    sessions.pop(key, None)

        if changed:
            _save(data)


def resolve_permission(session_id: str, agent_id: Optional[str] = None) -> str:
    """The permission mode in force for a session: its own, else the global one."""
    from agent.permission import global_mode, normalize_mode

    prefs = get_prefs(session_id, agent_id)
    if prefs.get("permission"):
        return normalize_mode(prefs["permission"], global_mode())
    return global_mode()
