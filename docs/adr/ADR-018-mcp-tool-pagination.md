# ADR 018: fix(mcp): follow paginated tool discovery cursors

## Context

tools/list supports pagination, but discovery currently uses only the first response. Tools on later pages never become available to the agent.

## Decision

Accumulate each tools/list page until nextCursor is absent and reject repeated cursors to avoid an endless discovery loop.

## Consequences

Servers with a single page retain existing behavior. A malformed cursor cycle follows the existing logged empty-list failure path.

## Acceptance

The regression in `tests/test_cow32_mcp_tool_pagination.py` fails on `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with this decision. Related existing tests must pass. Validation uses local fixtures without external services or model calls.
