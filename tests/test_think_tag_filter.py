"""<think> tag filtering for the final text and for streamed deltas."""

import pytest

from agent.protocol.agent_stream import AgentStreamExecutor


def _executor(inline=False):
    obj = AgentStreamExecutor.__new__(AgentStreamExecutor)
    obj._should_render_thinking_inline = lambda: inline
    obj._reset_think_stream()
    return obj


def _stream(chunks, inline=False):
    obj = _executor(inline)
    out = "".join(obj._filter_think_stream(c) for c in chunks)
    return out + obj._flush_think_stream()


@pytest.mark.parametrize("text, expected", [
    ("a<think>secret</think>b", "ab"),
    ("x<think>1</think>y<think>2</think>z", "xyz"),
    ("just a normal reply", "just a normal reply"),
    ("abc <think>partial reasoning", "abc ＜think＞partial reasoning"),
    ("text</think>more", "text＜/think＞more"),
    ("a<think>x</think>b</think>c", "ab＜/think＞c"),
])
def test_final_text(text, expected):
    assert _executor()._filter_think_tags(text) == expected


def test_final_text_inline_keeps_content():
    assert _executor(inline=True)._filter_think_tags("a<think>b</think>c") == "abc"


@pytest.mark.parametrize("chunks, expected", [
    (["hello", " world", ", all good"], "hello world, all good"),
    (["a<think>sec", "ret</think>b"], "ab"),
    (["before <thi", "nk>inner", "</thi", "nk> after"], "before  after"),
    (["a", "</think>", "b"], "a＜/think＞b"),
    (["abc<"], "abc<"),
    (["code <think> tag", " later"], "code ＜think＞ tag later"),
    (["a<think>reasoning"], "a＜think＞reasoning"),
])
def test_stream(chunks, expected):
    assert _stream(chunks) == expected


def test_split_open_tag_is_held_back():
    obj = _executor()
    assert obj._filter_think_stream("hi <thi") == "hi "
    assert obj._filter_think_stream("nk>hidden") == ""


def test_stream_inline_keeps_content():
    assert _stream(["a<thi", "nk>b</thi", "nk>c"], inline=True) == "abc"
