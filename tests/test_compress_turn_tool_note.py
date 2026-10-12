"""Compressing a turn keeps a note of the tools it called."""

from agent.protocol.message_utils import compress_turn_to_text_only


def _turn(*assistant_blocks):
    return {"messages": [
        {"role": "user", "content": [{"type": "text", "text": "save it"}]},
        *({"role": "assistant", "content": blocks} for blocks in assistant_blocks),
    ]}


def _tool(name):
    return {"type": "tool_use", "id": name, "name": name, "input": {}}


def test_tool_names_survive_in_call_order_without_duplicates():
    turn = _turn([_tool("write"), _tool("scheduler")], [_tool("write")],
                 [{"type": "text", "text": "Done."}])
    assistant = compress_turn_to_text_only(turn)["messages"][1]["content"]
    assert assistant[0]["text"] == "Done."
    assert assistant[1]["text"].endswith("write, scheduler]")


def test_turn_without_tools_is_unchanged():
    turn = _turn([{"type": "text", "text": "Hi."}])
    assert compress_turn_to_text_only(turn)["messages"][1]["content"] == [
        {"type": "text", "text": "Hi."}
    ]
