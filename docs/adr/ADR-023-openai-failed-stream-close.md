# ADR 023: fix(openai): close HTTP responses after failed streaming requests

Status: Accepted for this candidate.

## Context

Streaming HTTP 401, 429, and 5xx responses return before the response cleanup block. Repeated rejected or retried requests can retain open response connections.

## Decision

Put error-body handling inside a response cleanup block that also runs when the consumer closes the generator after the error chunk.

## Consequences

The existing structured error and successful stream behavior are preserved while every acquired response is closed.

## Validation

The focused regression fails on the unmodified base and passes with this change. tests/test_openai_failed_stream_close.py tests/test_openai_api_type.py passed locally; changed Python files passed CI-equivalent Ruff F checks. These are local native-contract checks using controlled doubles, not live provider or channel acceptance.
