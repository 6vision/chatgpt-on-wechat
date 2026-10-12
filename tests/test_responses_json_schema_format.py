"""Structured output requirements must survive a switch to Responses."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from models.openai.responses_adapter import build_responses_payload
from models.openai_compatible_bot import OpenAICompatibleBot


@pytest.mark.parametrize("strict", [True, False])
def test_json_schema_descriptor_is_flattened_without_mutation(strict):
    descriptor = {"name": "answer", "description": "An answer", "strict": strict,
                  "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                             "required": ["ok"], "additionalProperties": False}}
    response_format = {"type": "json_schema", "json_schema": descriptor}
    original = deepcopy(response_format)
    payload = build_responses_payload(model="test", messages=[], response_format=response_format)
    assert payload["text"]["format"] == {"type": "json_schema", **descriptor}
    assert response_format == original


def test_json_object_format_is_unchanged():
    payload = build_responses_payload(model="test", messages=[], response_format={"type": "json_object"})
    assert payload["text"]["format"] == {"type": "json_object"}


def test_no_format_remains_unspecified():
    assert "text" not in build_responses_payload(model="test", messages=[])


class Bot(OpenAICompatibleBot):
    def get_api_config(self):
        return {"model": "test", "api_type": "responses", "api_base": "https://test.invalid/v1"}


def test_native_bot_request_forwards_json_schema(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"status": "completed", "output": []}
    request = Mock(return_value=response)
    monkeypatch.setattr("models.openai.openai_http_client.requests.post", request)
    descriptor = {"name": "answer", "strict": True, "schema": {"type": "object", "properties": {}}}
    Bot().call_with_tools([{ "role": "user", "content": "Return an answer"}],
                          response_format={"type": "json_schema", "json_schema": descriptor})
    assert request.call_args.kwargs["json"]["text"]["format"] == {"type": "json_schema", **descriptor}
