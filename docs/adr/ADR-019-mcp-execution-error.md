# ADR 019: fix(mcp): propagate server tool execution errors

## Context

An MCP server result with isError true is returned as an ordinary successful tool result, so the agent and tool cards lose the failure status.

## Decision

Raise a dedicated execution-error exception for isError results; let McpTool convert it to ToolResult.fail while preserving the server explanation.

## Consequences

Tool-level failures become errors without changing existing JSON-RPC error string behavior or successful text results.

## Acceptance

The regression in `tests/test_cow32_mcp_execution_error.py` fails on `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with this decision. Related existing tests must pass. Validation uses local fixtures without external services or model calls.
