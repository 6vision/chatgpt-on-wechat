"""Regression tests for the ``<think>`` tag filter in streaming replies.

Some providers (e.g. MiniMax) wrap reasoning in ``<think>...</think>`` blocks.
Two failure modes are covered here:

1. **Final text**: an *unclosed* literal tag used to swallow everything after
   it, so a reply that merely mentioned the tag was truncated for the user.
   The final-text pass now keeps the tag in full-width form instead.
2. **Streaming**: a tag split across two deltas used to leak in half — a partial
   opening tag (``<thi``) was emitted as-is, and a standalone closing tag leaked
   as an orphan ``</think>``. Filtering is now stateful, holding back a
   suspicious trailing prefix until the next delta.
"""

import types

from agent.protocol.agent_stream import AgentStreamExecutor


# ---------------------------------------------------------------------------
# Final text: _filter_think_tags
# ---------------------------------------------------------------------------


def _run(text, streaming=False, render_inline=False):
    obj = AgentStreamExecutor.__new__(AgentStreamExecutor)  # bypass __init__
    obj._should_render_thinking_inline = lambda: render_inline
    return obj._filter_think_tags(text, streaming=streaming)


def test_paired_block_is_stripped():
    """A complete block loses both tags and content (unchanged behaviour)."""
    assert _run("a<think>secret</think>b") == "ab"


def test_unclosed_streaming_still_swallows():
    """Streaming: an unclosed tag keeps swallowing, so no half reasoning leaks."""
    assert _run("abc <think>partial reasoning", streaming=True) == "abc "


def test_unclosed_final_keeps_content_and_fullwidth_tag():
    """Final text: an unclosed tag must not swallow the rest of the reply."""
    out = _run("abc <think>partial reasoning")
    assert out == "abc ＜think＞partial reasoning"
    assert "partial reasoning" in out, "content must not be dropped"


def test_plain_text_passthrough():
    assert _run("just a normal reply") == "just a normal reply"


def test_render_inline_keeps_content_without_tags():
    """Inline thinking rendering strips the tags but keeps the content."""
    assert _run("a<think>b</think>c", render_inline=True) == "abc"


def test_multiple_paired_blocks():
    assert _run("x<think>1</think>y<think>2</think>z") == "xyz"


def test_final_orphan_close_tag_kept_fullwidth():
    """A closing tag without an opening counterpart is text, not markup.

    Paired blocks are removed first, so any closing tag left is an orphan; it is
    kept in full-width form rather than deleted, matching the unclosed-tag case.
    """
    obj = AgentStreamExecutor.__new__(AgentStreamExecutor)
    obj._should_render_thinking_inline = lambda: False
    assert obj._filter_think_tags("text</think>more") == "text＜/think＞more"
    assert obj._filter_think_tags("a<think>x</think>b</think>c") == "ab＜/think＞c"


# ---------------------------------------------------------------------------
# Streaming: stateful cross-delta filtering
# ---------------------------------------------------------------------------


def _make_streamer():
    obj = AgentStreamExecutor.__new__(AgentStreamExecutor)
    obj.model = types.SimpleNamespace(channel_type="telegram")  # non-inline path
    obj._reset_think_stream()
    return obj


def _stream(chunks):
    """Replay chunks the way production does; return (emitted, joined)."""
    obj = _make_streamer()
    emitted = []
    for c in chunks:
        d = obj._filter_think_stream(c)
        if d:
            emitted.append(d)
    tail = obj._flush_think_stream()
    if tail:
        emitted.append(tail)
    return emitted, "".join(emitted)


def test_open_tag_split_across_deltas():
    """A partial opening tag must never reach the channel."""
    emitted, full = _stream(["hello", " world", " <thi", "nk>reasoning", ", hidden"])
    assert "<thi" not in full and "<" not in "".join(emitted)
    assert full.startswith("hello world")


def test_close_tag_split_across_deltas():
    """A closing tag split across deltas must not leak, and its content is dropped."""
    emitted, full = _stream(["a<think>sec", "ret</think>b"])
    assert full == "ab"
    assert "</think>" not in full


def test_orphan_close_tag_alone():
    """A standalone closing tag is an orphan ⇒ kept full-width, not dropped."""
    emitted, full = _stream(["a", "</think>", "b"])
    assert full == "a＜/think＞b"


def test_normal_reply_unaffected():
    """A reply without tags must stream through unchanged."""
    emitted, full = _stream(["hello", " world", ", all good"])
    assert full == "hello world, all good"


def test_flush_does_not_drop_tail():
    """The flush must return buffered text, or the reply loses its ending."""
    emitted, full = _stream(["abc<"])
    assert full == "abc<"


def test_paired_block_split_across_deltas():
    """A complete block split across deltas is stripped entirely."""
    emitted, full = _stream(["before <thi", "nk>inner thoughts", "</thi", "nk> after"])
    assert "inner thoughts" not in full and "after" in full


def test_unclosed_literal_tag_does_not_truncate():
    """A literal unclosed tag must not swallow the rest of the stream.

    Dropping the buffered segment here would truncate ``full_content`` for good,
    since channels without a final-text pass have no way to recover it.
    """
    _em, full = _stream(["code shows <think> tag", "later content", "and more"])
    assert "later content" in full and "and more" in full, f"reply truncated: {full!r}"
    assert "＜think＞" in full, "literal tag should be kept full-width"


def test_truncated_in_think_flush_returns_content():
    """A stream cut off inside a block still hands its content back on flush."""
    _em, full = _stream(["a<think>reasoning"])
    assert "reasoning" in full and "＜think＞" in full, f"content lost: {full!r}"


def test_reset_clears_state():
    """Resetting must leave no tail/state behind for the next stream."""
    obj = _make_streamer()
    obj._filter_think_stream("<thi")
    assert obj._think_stream_tail == "<thi"
    obj._reset_think_stream()
    assert obj._think_stream_tail == "" and obj._think_stream_state == "normal"


def test_streaming_orphan_close_tag_kept_fullwidth():
    """The streaming path keeps a literal orphan closing tag too.

    Channels that accumulate deltas as the final text would otherwise lose a
    legitimate ``</think>`` written by the user.
    """
    _em, full = _stream(["code shows ", "</think>", " as a closing tag"])
    assert "＜/think＞" in full, f"literal text lost: {full!r}"


def test_inline_mode_keeps_thinking_content_streaming():
    """Inline mode (web + thinking enabled) keeps reasoning text while streaming.

    Guards the regression where a streaming filter that swallows inside a block
    would also swallow the inline-rendered reasoning panel.
    """
    obj = AgentStreamExecutor.__new__(AgentStreamExecutor)
    obj.model = types.SimpleNamespace(channel_type="web")
    obj._should_render_thinking_inline = lambda: True
    obj._reset_think_stream()
    emitted = []
    for c in ["a<thi", "nk>b</thi", "nk>c"]:
        d = obj._filter_think_stream(c)
        if d:
            emitted.append(d)
    tail = obj._flush_think_stream()
    if tail:
        emitted.append(tail)
    assert "".join(emitted) == "abc", f"inline content lost: {''.join(emitted)!r}"
