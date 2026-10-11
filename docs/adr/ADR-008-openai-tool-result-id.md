# ADR 008: fix(agent): drop tool results without a call identifier

Status: Proposed

## Context

The OpenAI history sanitizer drops unknown tool_call_id values but retains a role=tool message when the identifier is missing, null or empty. Providers require every tool result to name a preceding tool call, so one damaged row can invalidate the next request.

## Decision

Treat missing identifiers as orphaned results too, preserving valid matched results and other messages in their original order.

## Consequences

The change is confined to the affected contract and can be reverted independently. Existing behavior covered by the focused suite remains supported. No external API or model calls were used for validation.

## Validation

The new regression fails on base `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with the fix.

```text
...........................                                              [100%]
27 passed in 0.52s
```

Changed Python files pass the repository F-rule lint gate.
