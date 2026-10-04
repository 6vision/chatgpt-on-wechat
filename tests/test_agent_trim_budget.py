"""Regression tests for budget-aware context trimming (#3178).

``_trim_messages()`` used to drop the older half of turns (and fire a
summary LLM call) whenever turn count exceeded ``max_context_turns``,
even when the estimated token total was well under the model budget.

The trimming pass now enforces both constraints together:
- keep every complete turn while the history fits the input window *and*
  stays within ``max_context_turns``
- when over a limit, cut to TRIM_TARGET_RATIO of it (not half), so the next
  turns append without another trim and the prompt prefix stays cacheable
- apply ``max_context_turns`` as an explicit cost cap on what survives
- flush / summarize only when turns were actually discarded
"""

from types import SimpleNamespace

from agent.protocol.agent_stream import AgentStreamExecutor
from agent.protocol.message_utils import identify_complete_turns


class _MemoryManager:
    def __init__(self):
        self.flush_calls = []

    def flush_memory(self, **kwargs):
        self.flush_calls.append(kwargs)


def _make_turn_messages(turn_count):
    messages = []
    for i in range(turn_count):
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": f"q{i}"}],
        })
        messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": f"a{i}"}],
        })
    return messages


def _make_executor(
    *,
    turn_count,
    max_context_turns,
    tokens_per_message,
    max_tokens,
    messages=None,
):
    memory_manager = _MemoryManager()
    agent = SimpleNamespace(
        memory_manager=memory_manager,
        max_context_tokens=max_tokens,
        _get_model_context_window=lambda: max_tokens,
        _get_output_reserve_tokens=lambda: 0,
        _estimate_message_tokens=lambda message: tokens_per_message,
    )
    executor = AgentStreamExecutor.__new__(AgentStreamExecutor)
    executor.agent = agent
    executor.messages = messages if messages is not None else _make_turn_messages(turn_count)
    executor.system_prompt = "system"
    executor.max_context_turns = max_context_turns
    return executor, memory_manager


def _user_texts(messages):
    return [
        block["text"]
        for msg in messages
        if msg.get("role") == "user"
        for block in (msg.get("content") or [])
        if isinstance(block, dict) and block.get("type") == "text" and "text" in block
    ]


def test_many_short_turns_under_budget_do_not_summarize():
    """30 one-token turns fit both the 1000-token budget and the turn cap."""
    executor, memory_manager = _make_executor(
        turn_count=30,
        max_context_turns=30,
        tokens_per_message=1,
        max_tokens=1000,
    )

    executor._trim_messages()

    assert memory_manager.flush_calls == []
    assert len(identify_complete_turns(executor.messages)) == 30
    assert executor.messages[-1]["content"][0]["text"] == "a29"


def test_turn_cap_trims_even_when_under_token_budget():
    """31 tiny turns fit the token budget but exceed the turn cap.

    ``max_context_turns`` is an explicit cost limit, so older turns are still
    discarded (and summarized) even though the tokens would fit; the cut goes
    down to 24 turns (80% of the cap).
    """
    executor, memory_manager = _make_executor(
        turn_count=31,
        max_context_turns=30,
        tokens_per_message=1,
        max_tokens=1000,
    )

    executor._trim_messages()

    kept_turns = identify_complete_turns(executor.messages)
    assert len(kept_turns) == 24
    assert _user_texts(executor.messages) == [f"q{i}" for i in range(7, 31)]
    assert len(memory_manager.flush_calls) == 1
    assert _user_texts(memory_manager.flush_calls[0]["messages"]) == [f"q{i}" for i in range(7)]


def test_turns_after_a_trim_append_without_trimming_again():
    """The history prefix must stay put for a while after a trim.

    Dropping the oldest turn on every new message would change the start of
    the prompt each request, so the provider's prefix cache would never hit.
    """
    executor, memory_manager = _make_executor(
        turn_count=31,
        max_context_turns=30,
        tokens_per_message=1,
        max_tokens=1000,
    )
    executor._trim_messages()
    head = executor.messages[0]

    executor.messages.extend(_make_turn_messages(1))
    executor._trim_messages()

    assert executor.messages[0] is head
    assert len(identify_complete_turns(executor.messages)) == 25
    assert len(memory_manager.flush_calls) == 1


def test_over_budget_still_trims():
    """Turns that exceed the token budget must still be discarded."""
    executor, memory_manager = _make_executor(
        turn_count=10,
        max_context_turns=30,
        tokens_per_message=100,
        max_tokens=200,
    )

    executor._trim_messages()

    kept_turns = identify_complete_turns(executor.messages)
    assert len(kept_turns) < 10
    assert len(kept_turns) >= 1
    assert memory_manager.flush_calls, "over-budget trim should flush discarded turns"
    assert executor.messages[-1]["content"][0]["text"] == "a9"


def test_over_budget_trims_to_the_target_not_half():
    """Over budget, keep what fits 80% of the budget, not half of the turns.

    Each turn is 2 messages * 100 tokens = 200. System prompt is 100.
    max_tokens=3100 leaves a 3000-token turn budget; the 2400-token target
    keeps 12 of 20 turns. The old half-drop would keep 10.
    """
    executor, memory_manager = _make_executor(
        turn_count=20,
        max_context_turns=30,
        tokens_per_message=100,
        max_tokens=3100,
    )

    executor._trim_messages()

    kept_turns = identify_complete_turns(executor.messages)
    assert len(kept_turns) == 12
    assert _user_texts(executor.messages) == [f"q{i}" for i in range(8, 20)]
    assert executor.messages[-1]["content"][0]["text"] == "a19"
    assert len(memory_manager.flush_calls) == 1
    flushed = memory_manager.flush_calls[0]["messages"]
    assert _user_texts(flushed) == [f"q{i}" for i in range(8)]
    assert memory_manager.flush_calls[0]["reason"] == "trim"
    assert memory_manager.flush_calls[0]["context_summary_callback"] is not None


def test_over_budget_respects_max_context_turns_safety_net():
    """When already over budget, the turn cap still bounds what is kept.

    20 turns * 20 tokens = 400, system = 10, max_tokens=250 -> 240-token
    budget, 192-token target keeps 9 turns. The turn target (80% of 8) then
    caps at 6.
    """
    executor, memory_manager = _make_executor(
        turn_count=20,
        max_context_turns=8,
        tokens_per_message=10,
        max_tokens=250,
    )

    executor._trim_messages()

    kept_turns = identify_complete_turns(executor.messages)
    assert len(kept_turns) == 6
    assert _user_texts(executor.messages) == [f"q{i}" for i in range(14, 20)]
    assert executor.messages[-1]["content"][0]["text"] == "a19"
    assert memory_manager.flush_calls


def test_single_turn_over_budget_is_kept_without_flush():
    """A single oversized turn is kept so the current exchange is not lost."""
    executor, memory_manager = _make_executor(
        turn_count=1,
        max_context_turns=30,
        tokens_per_message=100,
        max_tokens=50,
    )

    executor._trim_messages()

    assert len(identify_complete_turns(executor.messages)) == 1
    assert executor.messages[-1]["content"][0]["text"] == "a0"
    assert memory_manager.flush_calls == []


def test_trim_keeps_tool_use_and_tool_result_together():
    """Discarded older turns must not split a kept tool_use/tool_result pair."""
    messages = _make_turn_messages(2)
    messages.extend([
        {"role": "user", "content": [{"type": "text", "text": "q2"}]},
        {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": "call_1",
                "name": "ls",
                "input": {"path": "."},
            }],
        },
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "call_1",
                "content": "file.txt",
            }],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "a2"}]},
    ])
    executor, memory_manager = _make_executor(
        turn_count=3,
        max_context_turns=30,
        tokens_per_message=100,
        max_tokens=500,
        messages=messages,
    )

    executor._trim_messages()

    kept_turns = identify_complete_turns(executor.messages)
    assert len(kept_turns) == 2
    block_types = [
        block.get("type")
        for msg in executor.messages
        for block in (msg.get("content") or [])
        if isinstance(block, dict)
    ]
    assert "tool_use" in block_types
    assert "tool_result" in block_types
    assert executor.messages[-1]["content"][0]["text"] == "a2"
    assert memory_manager.flush_calls
    assert _user_texts(memory_manager.flush_calls[0]["messages"]) == ["q0"]


def test_previous_turn_is_kept_as_text_when_only_the_current_fits():
    """A previous turn too big for the budget is reduced to text, not dropped.

    System 100 + current 200 fit max_tokens=400, the previous turn's tool
    chain does not. Without it the Agent would not know what "yes" answers.
    """
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "q0"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "a0"}]},
        {"role": "user", "content": [{"type": "text", "text": "delete the old logs?"}]},
        {"role": "assistant", "content": [{
            "type": "tool_use", "id": "call_1", "name": "ls", "input": {"path": "logs"},
        }]},
        {"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": "call_1", "content": "a.log b.log",
        }]},
        {"role": "assistant", "content": [{"type": "text", "text": "Found 2 logs, delete them?"}]},
        {"role": "user", "content": [{"type": "text", "text": "yes"}]},
    ]
    executor, memory_manager = _make_executor(
        turn_count=3,
        max_context_turns=30,
        tokens_per_message=100,
        max_tokens=400,
        messages=messages,
    )

    executor._trim_messages()

    assert _user_texts(executor.messages) == ["delete the old logs?", "yes"]
    assert executor.messages[1]["content"][0]["text"] == "Found 2 logs, delete them?"
    block_types = {
        block.get("type")
        for msg in executor.messages
        for block in (msg.get("content") or [])
        if isinstance(block, dict)
    }
    assert block_types == {"text"}
    assert _user_texts(memory_manager.flush_calls[0]["messages"]) == ["q0"]
