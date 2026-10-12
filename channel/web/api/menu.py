"""/api/menu: the console menu the user arranged.

One document for the whole instance, read by both the web console and the
desktop client. Until the user saves one there is none, and each client draws
its own built-in menu. The document holds groups of items, and an item is one
of:

- ``builtin``: a page of the client, named by ``view``. A client skips the
  views it does not have, and keeps them when it saves.
- ``artifact``: a file shown in place, by its absolute path.
- ``url``: a web page, shown in place (``open: embed``) or in a new tab.

Only the layout is stored. What a client needs to show an artifact (its kind,
whether it still exists, the preview URL) is worked out on every read.
"""

import json
import os
import re
from urllib.parse import quote, urlparse

import web

from channel.web.core._common import _build_preview_url, _is_path_allowed, _require_auth
from common.log import logger

MAX_GROUPS = 20
MAX_ITEMS = 200
TITLE_MAX = 40
URL_MAX = 2048

ITEM_TYPES = ("builtin", "artifact", "url")
OPEN_MODES = ("embed", "tab")
# Artifacts that read as a page of their own when opened from the menu.
MENU_KINDS = ("html", "markdown")
# Pages a menu must always lead to, or the user could hide their way out of
# the very settings that bring the menu back.
REQUIRED_VIEWS = ("chat", "config")

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_VIEW_RE = re.compile(r"^[a-z_]{1,30}$")
_ICON_RE = re.compile(r"^[a-z0-9-]{0,40}$")


def _title(value) -> str:
    return " ".join(str(value or "").split())[:TITLE_MAX]


def _clean_item(raw: dict, seen_ids: set, seen_views: set) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("an item must be an object")
    item_id = str(raw.get("id") or "")
    if not _ID_RE.match(item_id) or item_id in seen_ids:
        raise ValueError(f"bad or repeated item id: {item_id!r}")
    seen_ids.add(item_id)
    kind = raw.get("type")
    if kind not in ITEM_TYPES:
        raise ValueError(f"unknown item type: {kind!r}")
    icon = str(raw.get("icon") or "")
    if not _ICON_RE.match(icon):
        raise ValueError(f"bad icon: {icon!r}")
    item = {"id": item_id, "type": kind, "title": _title(raw.get("title")), "icon": icon}

    if kind == "builtin":
        view = str(raw.get("view") or "")
        if not _VIEW_RE.match(view) or view in seen_views:
            raise ValueError(f"bad or repeated view: {view!r}")
        seen_views.add(view)
        item["view"] = view
        item["hidden"] = bool(raw.get("hidden")) and view not in REQUIRED_VIEWS
    elif kind == "artifact":
        path = os.path.expanduser(str(raw.get("path") or ""))
        if not path or len(path) > URL_MAX or not os.path.isabs(path):
            raise ValueError("an artifact needs an absolute path")
        from agent.protocol.artifact import classify_kind

        if classify_kind(path) not in MENU_KINDS:
            raise ValueError("only web pages and markdown documents can go in the menu")
        item["path"] = path
    else:
        url = str(raw.get("url") or "").strip()
        parsed = urlparse(url)
        if len(url) > URL_MAX or parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"not an http(s) link: {url!r}")
        item["url"] = url
        item["open"] = raw.get("open") if raw.get("open") in OPEN_MODES else "embed"
    if kind != "builtin" and not item["title"]:
        raise ValueError("a custom item needs a title")
    return item


def clean_menu(raw) -> dict:
    """The stored form of a menu the client sent, or ValueError."""
    if not isinstance(raw, dict) or not isinstance(raw.get("groups"), list):
        raise ValueError("menu must be an object with a groups list")
    if len(raw["groups"]) > MAX_GROUPS:
        raise ValueError("too many groups")
    seen_groups, seen_ids, seen_views = set(), set(), set()
    groups = []
    for g in raw["groups"]:
        if not isinstance(g, dict) or not isinstance(g.get("items", []), list):
            raise ValueError("a group must be an object with an items list")
        group_id = str(g.get("id") or "")
        if not _ID_RE.match(group_id) or group_id in seen_groups:
            raise ValueError(f"bad or repeated group id: {group_id!r}")
        seen_groups.add(group_id)
        items = [_clean_item(i, seen_ids, seen_views) for i in g.get("items", [])]
        groups.append({"id": group_id, "title": _title(g.get("title")), "items": items})
    if len(seen_ids) > MAX_ITEMS:
        raise ValueError("too many items")
    return {"version": 1, "groups": groups}


def _describe_artifact(path: str) -> dict:
    """What a client needs to show the file right now."""
    from agent.protocol.artifact import classify_kind, is_previewable

    real = os.path.realpath(path)
    exists = os.path.isfile(real) and _is_path_allowed(real)
    kind = classify_kind(path)
    version = 0
    if exists:
        try:
            version = int(os.stat(real).st_mtime)
        except OSError:
            exists = False
    return {
        "file_name": os.path.basename(path),
        "kind": kind,
        "exists": exists,
        "previewable": exists and is_previewable(kind),
        "raw_url": f"/api/file?path={quote(path)}&v={version}" if exists else "",
        "preview_url": _build_preview_url(path) if exists else "",
    }


def load_menu():
    from common.state_dir import menu_file

    path = menu_file()
    if not path.is_file():
        return None
    try:
        return clean_menu(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        # A hand-edited file that no longer parses must not take the console's
        # navigation down with it: fall back to the built-in menu.
        logger.warning(f"[WebChannel] Ignoring unreadable menu file: {e}")
        return None


def _with_files(menu):
    if not menu:
        return menu
    for group in menu["groups"]:
        for item in group["items"]:
            if item["type"] == "artifact":
                item["file"] = _describe_artifact(item["path"])
    return menu


class MenuHandler:
    """GET /api/menu -> {menu: null | {groups}}; POST {menu} saves, {menu: null} resets."""

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            return json.dumps({"status": "success", "menu": _with_files(load_menu())}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Menu read error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from common.atomic_write import write_json_atomic
            from common.state_dir import menu_file

            body = json.loads(web.data() or b"{}")
            path = menu_file()
            if body.get("menu") is None:
                if path.is_file():
                    path.unlink()
                return json.dumps({"status": "success", "menu": None})
            menu = clean_menu(body["menu"])
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(str(path), menu, indent=2)
            return json.dumps({"status": "success", "menu": _with_files(menu)}, ensure_ascii=False)
        except ValueError as e:
            return json.dumps({"status": "error", "message": str(e)})
        except Exception as e:
            logger.error(f"[WebChannel] Menu save error: {e}")
            return json.dumps({"status": "error", "message": str(e)})
