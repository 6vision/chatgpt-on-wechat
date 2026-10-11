import pytest
from agent.protocol.message_utils import drop_orphaned_tool_results_openai

@pytest.mark.parametrize("identifier", [None, "", "missing"])
def test_orphaned_tool_message_cannot_reach_provider(identifier):
    query = {"role": "user", "content": "hello"}
    orphan = {"role": "tool", "content": "orphan"}
    if identifier is not None:
        orphan["tool_call_id"] = identifier
    original = [query, orphan]
    assert drop_orphaned_tool_results_openai(original) == [query]
    assert original == [query, orphan]

def test_matched_result_and_plain_messages_are_preserved():
    messages = [{"role": "assistant", "tool_calls": [{"id": "t1"}]},
                {"role": "tool", "tool_call_id": "t1", "content": "real output"},
                {"role": "assistant", "content": "answer"}]
    assert drop_orphaned_tool_results_openai(messages) == messages

def test_result_before_its_call_is_still_orphaned():
    call = {"role": "assistant", "tool_calls": [{"id": "t1"}]}
    result = {"role": "tool", "tool_call_id": "t1", "content": "premature"}
    assert drop_orphaned_tool_results_openai([result, call]) == [call]
