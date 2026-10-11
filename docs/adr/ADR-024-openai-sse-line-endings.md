# ADR 024: fix(openai): frame SSE events by valid line endings

Status: Accepted for this candidate.

## Context

The model SSE decoder only recognizes three fixed blank-line byte sequences. Legal mixed LF/CR line endings merge separate JSON events, an initial BOM drops the first data field, and Unicode separators inside JSON are mistaken for framing by str.splitlines().

## Decision

Read SSE lines using only CR, LF, and CRLF delimiters, retain partial UTF-8 lines across network chunks, and strip the one allowed initial BOM. Continue accepting the existing unterminated proxy event compatibility case.

## Consequences

Native model streams preserve their original Unicode payload and dispatch mixed line endings independently. No protocol or request shape changes.

## Validation

The focused regression fails on the unmodified base and passes with this change. tests/test_openai_sse_line_endings.py tests/test_openai_api_type.py passed locally; changed Python files passed CI-equivalent Ruff F checks. These are local native-contract checks using controlled doubles, not live provider or channel acceptance.
