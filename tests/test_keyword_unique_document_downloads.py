"""Pending keyword file replies must not overwrite one another's bytes."""
import importlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import plugins
from bridge.context import Context, ContextType
from bridge.reply import ReplyType
from plugins import Event, EventContext

plugins.instance.current_plugin_path = "./plugins/keyword"
keyword_module = importlib.import_module("plugins.keyword.keyword")
plugins.instance.current_plugin_path = None
Keyword = plugins.instance.plugins["KEYWORD"]


def handle(url):
    plugin = Keyword.__new__(Keyword)
    plugin.keyword = {"download": url}
    event = EventContext(Event.ON_HANDLE_CONTEXT, {"context": Context(ContextType.TEXT, "download"), "reply": None})
    plugin.on_handle_context(event)
    return event["reply"]


def test_two_urls_with_same_basename_retain_each_document(monkeypatch, tmp_path):
    monkeypatch.setattr(keyword_module.state_dir, "tmp_dir", lambda: tmp_path)
    monkeypatch.setattr(keyword_module.requests, "get", lambda url, **kwargs: SimpleNamespace(status_code=200, content=url.encode()))
    first = handle("https://one.invalid/report.pdf")
    second = handle("https://two.invalid/report.pdf")
    assert first.type is second.type is ReplyType.FILE
    assert first.content != second.content
    assert Path(first.content).read_bytes() == b"https://one.invalid/report.pdf"
    assert Path(second.content).read_bytes() == b"https://two.invalid/report.pdf"
    assert Path(first.content).name == Path(second.content).name == "report.pdf"


def test_simultaneous_downloads_keep_all_reply_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(keyword_module.state_dir, "tmp_dir", lambda: tmp_path)
    monkeypatch.setattr(keyword_module.requests, "get", lambda url, **kwargs: SimpleNamespace(status_code=200, content=url.encode()))
    urls = [f"https://host{i}.invalid/report.pdf" for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        replies = list(pool.map(handle, urls))
    assert len({reply.content for reply in replies}) == len(urls)
    for url, reply in zip(urls, replies):
        assert Path(reply.content).read_bytes() == url.encode()
