# ADR 009: fix(agent): preserve matched results when removing orphan blocks

Status: Proposed

## Context

A Claude-format user message can contain a valid tool result alongside an orphaned result. The sanitizer removes the entire result-only message when any block is orphaned, then synthesizes an error for the valid call and loses its actual output.

## Decision

Remove only unmatched result blocks. Retain valid results and other content; discard the message only when no blocks remain. Re-running the sanitizer on the repaired history is stable.

## Consequences

The change is confined to the affected contract and can be reverted independently. Existing behavior covered by the focused suite remains supported. No external API or model calls were used for validation.

## Validation

The new regression fails on base `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with the fix.

```text
..........................                                               [100%]
26 passed in 0.48s
```

Changed Python files pass the repository F-rule lint gate.
