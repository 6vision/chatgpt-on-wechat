from models.openai.responses_adapter import responses_to_chat_completion


def test_refusal_survives_response_translation():
    result = responses_to_chat_completion(
        {
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "refusal", "refusal": "Cannot assist with this request."}]}
            ],
        }
    )
    assert result["choices"][0]["message"]["content"] == "Cannot assist with this request."


def test_normal_text_unchanged():
    result = responses_to_chat_completion(
        {"output": [{"type": "message", "content": [{"type": "output_text", "text": "hello"}]}]}
    )
    assert result["choices"][0]["message"]["content"] == "hello"


def test_stream_refusal_survives_translation():
    from models.openai.responses_adapter import responses_stream_to_chat_chunks

    events = [
        {"type": "response.refusal.delta", "delta": "Cannot assist."},
        {"type": "response.completed", "response": {"status": "completed"}},
    ]
    chunks = list(responses_stream_to_chat_chunks(iter(events)))
    assert chunks[0]["choices"][0]["delta"]["content"] == "Cannot assist."
