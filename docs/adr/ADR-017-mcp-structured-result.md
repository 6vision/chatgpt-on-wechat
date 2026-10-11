# ADR 017: fix(mcp): retain structured-only tool results

## Context

MCP tool calls read only text content blocks, returning an empty success when a server provides structuredContent without a redundant text block.

## Decision

Serialize structuredContent as JSON when there are no text blocks, preserving the existing text result when provided.

## Consequences

Structured tool data reaches the model, including empty JSON objects. Existing text responses retain their string format.

## Acceptance

The regression in `tests/test_cow32_mcp_structured_result.py` fails on `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with this decision. Related existing tests must pass. Validation uses local fixtures without external services or model calls.
