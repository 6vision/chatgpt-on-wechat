import json
from unittest.mock import patch

import pytest

from channel.web.api import menu as menu_api
from channel.web.api.menu import MenuHandler, clean_menu


def _menu(*items, group_id="main", title=""):
    return {"groups": [{"id": group_id, "title": title, "items": list(items)}]}


def _builtin(view, **extra):
    return {"id": view, "type": "builtin", "view": view, **extra}


def test_a_menu_keeps_only_the_layout_fields():
    menu = clean_menu(_menu(
        _builtin("chat", junk=1),
        {"id": "dash", "type": "url", "url": "https://example.com/d", "title": "  Sales   dash ",
         "open": "tab", "file": {"preview_url": "/x"}},
    ))
    assert menu == {"version": 1, "groups": [{"id": "main", "title": "", "items": [
        {"id": "chat", "type": "builtin", "title": "", "icon": "", "view": "chat", "hidden": False},
        {"id": "dash", "type": "url", "title": "Sales dash", "icon": "", "url": "https://example.com/d", "open": "tab"},
    ]}]}


def test_the_pages_that_bring_the_menu_back_cannot_be_hidden():
    menu = clean_menu(_menu(_builtin("chat", hidden=True), _builtin("config", hidden=True),
                            _builtin("logs", hidden=True)))
    assert [i["hidden"] for i in menu["groups"][0]["items"]] == [False, False, True]


@pytest.mark.parametrize("item", [
    {"id": "x", "type": "url", "url": "javascript:alert(1)", "title": "x"},
    {"id": "x", "type": "url", "url": "file:///etc/passwd", "title": "x"},
    {"id": "x", "type": "url", "url": "https://example.com"},
    {"id": "x", "type": "artifact", "path": "relative/a.html", "title": "x"},
    {"id": "x", "type": "artifact", "path": "/tmp/poster.png", "title": "x"},
    {"id": "x", "type": "artifact", "path": "/tmp/report.docx", "title": "x"},
    {"id": "x", "type": "frame", "title": "x"},
    {"id": "bad id", "type": "builtin", "view": "chat"},
    {"id": "x", "type": "builtin", "view": "chat", "icon": "<svg>"},
])
def test_a_bad_item_is_refused(item):
    with pytest.raises(ValueError):
        clean_menu(_menu(item))


def test_ids_and_views_are_unique_across_groups():
    with pytest.raises(ValueError):
        clean_menu({"groups": [{"id": "a", "items": [_builtin("chat")]},
                               {"id": "b", "items": [_builtin("chat")]}]})
    with pytest.raises(ValueError):
        clean_menu({"groups": [{"id": "a", "items": []}, {"id": "a", "items": []}]})


@pytest.fixture
def menu_path(tmp_path):
    path = tmp_path / "system" / "menu.json"
    with patch("common.state_dir.menu_file", return_value=path), \
         patch("channel.web.api.menu._require_auth"):
        yield path


def _post(menu):
    with patch("channel.web.api.menu.web.data", return_value=json.dumps({"menu": menu}).encode()), \
         patch("channel.web.api.menu.web.header"):
        return json.loads(MenuHandler().POST())


def _get():
    with patch("channel.web.api.menu.web.header"):
        return json.loads(MenuHandler().GET())


def test_no_saved_menu_leaves_each_client_its_own(menu_path):
    assert _get() == {"status": "success", "menu": None}


def test_a_saved_menu_is_read_back_with_what_its_files_need(menu_path, tmp_path):
    page = tmp_path / "out" / "dash.html"
    page.parent.mkdir()
    page.write_text("<p>hi</p>", encoding="utf-8")
    with patch.object(menu_api, "_is_path_allowed", return_value=True):
        saved = _post(_menu(_builtin("chat"),
                            {"id": "d", "type": "artifact", "path": str(page), "title": "Dash"},
                            {"id": "gone", "type": "artifact", "path": str(tmp_path / "gone.md"), "title": "Gone"}))
        read = _get()
    assert saved["status"] == "success"
    on_disk = json.loads(menu_path.read_text(encoding="utf-8"))
    assert "file" not in on_disk["groups"][0]["items"][1]

    dash, gone = read["menu"]["groups"][0]["items"][1:]
    assert dash["file"]["kind"] == "html" and dash["file"]["exists"]
    assert dash["file"]["preview_url"].startswith("/preview/")
    assert gone["file"]["exists"] is False and gone["file"]["preview_url"] == ""


def test_a_file_outside_the_served_roots_is_not_offered(menu_path, tmp_path):
    page = tmp_path / "secret.html"
    page.write_text("x", encoding="utf-8")
    with patch.object(menu_api, "_is_path_allowed", return_value=False):
        _post(_menu({"id": "s", "type": "artifact", "path": str(page), "title": "S"}))
        item = _get()["menu"]["groups"][0]["items"][0]
    assert item["file"]["exists"] is False and item["file"]["preview_url"] == ""


def test_a_bad_menu_is_refused_and_the_saved_one_kept(menu_path):
    _post(_menu(_builtin("chat")))
    before = menu_path.read_text(encoding="utf-8")
    result = _post(_menu({"id": "x", "type": "url", "url": "ftp://a", "title": "x"}))
    assert result["status"] == "error"
    assert menu_path.read_text(encoding="utf-8") == before


def test_resetting_removes_the_saved_menu(menu_path):
    _post(_menu(_builtin("chat")))
    assert _post(None) == {"status": "success", "menu": None}
    assert not menu_path.exists()
    assert _get()["menu"] is None


def test_an_unreadable_file_falls_back_to_the_built_in_menu(menu_path):
    menu_path.parent.mkdir(parents=True)
    menu_path.write_text("{not json", encoding="utf-8")
    assert _get()["menu"] is None
