# ADR 025: fix(openai): preserve function controls when adapting Responses requests

Status: Accepted for this candidate.

## Context

The shared bot forwards Chat-Completions-shaped forced function choices unchanged to Responses, which expects the function name at the top level. The same function translation drops explicit strict true/false settings.

## Decision

Flatten nested forced function choices and carry the function strict flag through both supported tool definition shapes. Preserve caller-owned dictionaries and existing string or already-flat choices.

## Consequences

Forced function requests use the native Responses schema and explicit non-strict settings remain authoritative. Chat Completions requests are unaffected.

## Validation

The focused regression fails on the unmodified base and passes with this change. tests/test_responses_function_contract.py tests/test_openai_api_type.py passed locally; changed Python files passed CI-equivalent Ruff F checks. These are local native-contract checks using controlled doubles, not live provider or channel acceptance.
