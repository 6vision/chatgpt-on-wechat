"""The stream parser must accept every common reasoning field name."""
# encoding:utf-8
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.protocol.agent_stream import AgentStreamExecutor


def _make_executor(chunks, events, thinking_enabled=True):
    class _Model:
        model = "test-model"

        def call_stream(self, request):
            for chunk in chunks:
                yield chunk

    class _Exec(AgentStreamExecutor):
        def _is_thinking_enabled(self):
            return thinking_enabled

        def _trim_messages(self):
            return None

        def _validate_and_fix_messages(self):
            return None

        def _catalog_max_output_tokens(self):
            return 16

        def _filter_think_tags(self, text):
            return text

    return _Exec(
        agent=SimpleNamespace(),
        model=_Model(),
        system_prompt="",
        tools=[],
        max_turns=2,
        messages=[],
        on_event=events.append,
    )


def _reasoning_updates(events):
    return [
        e["data"]["delta"]
        for e in events
        if e.get("type") == "reasoning_update"
    ]


def test_reasoning_field_is_routed_to_the_thinking_channel():
    events = []
    executor = _make_executor(
        [
            {"choices": [{"delta": {"reasoning": "let me "}}]},
            {"choices": [{"delta": {"reasoning": "count"}}]},
            {"choices": [{"delta": {"content": "42"}}]},
        ],
        events,
    )

    text, tool_calls, _ = executor._call_llm_stream(retry_on_empty=False)

    assert text == "42"
    assert tool_calls == []
    assert _reasoning_updates(events) == ["let me ", "count"]

    assistant = executor.messages[-1]
    thinking = [b for b in assistant["content"] if b["type"] == "thinking"]
    assert thinking and thinking[0]["thinking"] == "let me count"
    visible = [b["text"] for b in assistant["content"] if b["type"] == "text"]
    assert visible == ["42"]


def test_reasoning_content_still_wins_over_reasoning():
    events = []
    executor = _make_executor(
        [
            {"choices": [{"delta": {
                "reasoning_content": "preferred",
                "reasoning": "ignored",
            }}]},
            {"choices": [{"delta": {"content": "ok"}}]},
        ],
        events,
    )

    executor._call_llm_stream(retry_on_empty=False)

    assert _reasoning_updates(events) == ["preferred"]


def test_thinking_field_is_also_accepted():
    events = []
    executor = _make_executor(
        [
            {"choices": [{"delta": {"thinking": "hmm"}}]},
            {"choices": [{"delta": {"content": "done"}}]},
        ],
        events,
    )

    executor._call_llm_stream(retry_on_empty=False)

    assert _reasoning_updates(events) == ["hmm"]


def test_list_shaped_reasoning_does_not_crash():
    events = []
    executor = _make_executor(
        [
            {"choices": [{"delta": {"reasoning": [
                {"type": "reasoning", "reasoning": "block one"},
                {"type": "reasoning", "reasoning": " block two"},
            ]}}]},
            {"choices": [{"delta": {"content": "answer"}}]},
        ],
        events,
    )

    text, _, _ = executor._call_llm_stream(retry_on_empty=False)

    assert text == "answer"
    assert _reasoning_updates(events) == ["block one block two"]

def test_non_string_reasoning_is_ignored():
    events = []
    executor = _make_executor(
        [
            {"choices": [{"delta": {"thinking": {"type": "enabled"}}}]},
            {"choices": [{"delta": {"content": "answer"}}]},
        ],
        events,
    )

    text, _, _ = executor._call_llm_stream(retry_on_empty=False)

    assert text == "answer"
    assert _reasoning_updates(events) == []
