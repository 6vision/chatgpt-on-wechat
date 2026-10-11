# ADR 011: fix(memory): isolate malformed vectors during retrieval

Status: Proposed

## Context

A single malformed persisted embedding raises while decoding or scoring every search row, so healthy vectors become unavailable. Nonfinite vectors can also occupy the top-k partition and crowd out valid matches.

## Decision

Validate and normalize each decoded vector locally, skip malformed or nonfinite rows with a diagnostic, and continue scoring healthy rows. Apply the same behavior to NumPy and pure-Python retrieval.

## Consequences

The change is confined to the affected contract and can be reverted independently. Existing behavior covered by the focused suite remains supported. No external API or model calls were used for validation.

## Validation

The new regression fails on base `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with the fix.

```text
............                                                             [100%]
12 passed in 0.19s
```

Changed Python files pass the repository F-rule lint gate.
