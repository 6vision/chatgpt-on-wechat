from models.openai.responses_adapter import responses_to_chat_completion, responses_stream_to_chat_chunks


def test_nonstream_truncated_tool_call_reports_length():
    result = responses_to_chat_completion(
        {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"type": "function_call", "call_id": "c", "name": "read", "arguments": "{"}],
        }
    )
    assert result["choices"][0]["finish_reason"] == "length"


def test_stream_truncated_tool_call_reports_length():
    events = [
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {"type": "function_call", "call_id": "c", "name": "read"},
        },
        {
            "type": "response.incomplete",
            "response": {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
        },
    ]
    assert list(responses_stream_to_chat_chunks(iter(events)))[-1]["choices"][0]["finish_reason"] == "length"


def test_completed_tool_call_unchanged():
    result = responses_to_chat_completion(
        {"status": "completed", "output": [{"type": "function_call", "name": "read", "arguments": "{}"}]}
    )
    assert result["choices"][0]["finish_reason"] == "tool_calls"
