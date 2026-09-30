"""A banwords.txt carrying a UTF-8 BOM must not silence its first word.

``plugins/banwords/banwords.txt`` is gitignored and user-built, and on
Windows Notepad / PowerShell write UTF-8 with a BOM by default. The wordlist
is read line by line with plain ``utf-8``, so the file's first line comes
out as ``\\ufeffword`` -- ``str.strip()`` does not remove U+FEFF (it is not
whitespace), the word is registered with the BOM glued to it, and it can
never match a real message. There is no error: the first word of the list
is silently unfiltered.

``agent/admin.py`` already reads user-edited files with ``utf-8-sig`` for
exactly this reason ("utf-8-sig tolerates a UTF-8 BOM (e.g. config.json
edited with Windows Notepad / PowerShell)"); ``agent/team.py`` and
``channel/feishu/feishu_channel.py`` follow the same convention. This
applies it to the wordlist read too.

The test points the plugin at ``tmp_path``: ``__file__`` decides where the
plugin looks for banwords.txt, and the class-level ``path`` decides where
``load_config`` looks for config.json (patched away entirely via ``pconf``).
"""
import importlib

import pytest

import plugins


@pytest.fixture(autouse=True)
def _isolate_plugin_global_config(monkeypatch):
    """``Plugin.load_config`` starts at the global plugins/config.json."""
    monkeypatch.setattr("plugins.plugin.pconf", lambda name: None)


def _instantiate_banwords(tmp_path, monkeypatch):
    plugins.instance.current_plugin_path = str(tmp_path)
    try:
        module = importlib.import_module("plugins.banwords.banwords")
    finally:
        plugins.instance.current_plugin_path = None
    plugin_cls = plugins.instance.plugins["BANWORDS"]
    monkeypatch.setattr(module, "__file__", str(tmp_path / "banwords.py"))
    monkeypatch.setattr(plugin_cls, "path", str(tmp_path))
    return plugin_cls()


def _write_wordlist(tmp_path, bom):
    """Two words: the first rides on the BOM, the second is the control."""
    body = "百度\n腾讯\n".encode("utf-8")
    (tmp_path / "banwords.txt").write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)


def test_first_word_of_a_bom_wordlist_is_still_filtered(tmp_path, monkeypatch):
    _write_wordlist(tmp_path, bom=True)
    plugin = _instantiate_banwords(tmp_path, monkeypatch)
    hit = plugin.searchr.FindFirst("帮我查一下 百度 的股价")
    assert hit is not None, "the first word of a BOM wordlist must still be filtered"
    assert hit["Keyword"] == "百度"


def test_bomless_wordlist_keeps_working(tmp_path, monkeypatch):
    _write_wordlist(tmp_path, bom=False)
    plugin = _instantiate_banwords(tmp_path, monkeypatch)
    assert plugin.searchr.FindFirst("帮我查一下 百度 的股价") is not None
    assert plugin.searchr.FindFirst("帮我查一下 腾讯 的股价") is not None
