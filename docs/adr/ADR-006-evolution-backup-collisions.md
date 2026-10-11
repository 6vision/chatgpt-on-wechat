# ADR 006: fix(evolution): give each undo snapshot a unique directory

Status: Proposed

## Context

Backup IDs have only millisecond precision and mkdir accepts an existing directory. Two evolution snapshots taken in the same millisecond share their manifest and payload files, replacing the earlier undo state.

## Decision

Keep the sortable timestamp prefix, append a collision-resistant numeric UUID suffix compatible with existing restore IDs, and refuse reuse of a snapshot directory.

## Consequences

The change is confined to the affected contract and can be reverted independently. Existing behavior covered by the focused suite remains supported. No external API or model calls were used for validation.

## Validation

The new regression fails on base `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with the fix.

```text
....                                                                     [100%]
4 passed in 0.23s
```

Changed Python files pass the repository F-rule lint gate.
