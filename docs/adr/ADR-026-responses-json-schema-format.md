# ADR 026: fix(openai): retain JSON schema output constraints on Responses

Status: Accepted for this candidate.

## Context

call_with_tools accepts response_format and forwards it to the Responses adapter, but the adapter only handles json_object. A json_schema requirement is silently discarded when the configured API uses Responses.

## Decision

Translate the nested Chat-Completions json_schema descriptor into the flat Responses text.format object, preserving name, description, schema, and explicit strict settings.

## Consequences

Structured output callers retain their requested schema through Responses routing. Existing JSON object and unspecified format behavior are unchanged.

## Validation

The focused regression fails on the unmodified base and passes with this change. tests/test_responses_json_schema_format.py tests/test_openai_api_type.py passed locally; changed Python files passed CI-equivalent Ruff F checks. These are local native-contract checks using controlled doubles, not live provider or channel acceptance.
