# ADR 007: fix(workspace): recover session preferences from non-object JSON

Status: Proposed

## Context

session_prefs.json can be valid JSON with a list, string or number at its root. _load calls .get on that value, so reading chat preferences, setting a model and deleting a session all crash instead of recovering like the sibling project store.

## Decision

Treat a parsed non-object root as an empty preferences store. Read-only access leaves the original file untouched; a subsequent explicit update persists a valid object.

## Consequences

The change is confined to the affected contract and can be reverted independently. Existing behavior covered by the focused suite remains supported. No external API or model calls were used for validation.

## Validation

The new regression fails on base `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with the fix.

```text
..........                                                               [100%]
10 passed in 0.61s
```

Changed Python files pass the repository F-rule lint gate.
