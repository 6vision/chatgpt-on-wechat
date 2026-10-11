# ADR 010: fix(memory): reject incomplete or ambiguously indexed embedding batches

Status: Proposed

## Context

embed_batch accepts fewer vectors than requested and duplicate response indexes. Memory indexing zips vectors with chunks, silently losing tail chunks or associating a vector with the wrong text when a provider returns a malformed batch.

## Decision

Require one response item per input and, when indexes are present, require a complete integer permutation of the page positions. Continue supporting fully indexless gateways and correctly reordered paginated results.

## Consequences

The change is confined to the affected contract and can be reverted independently. Existing behavior covered by the focused suite remains supported. No external API or model calls were used for validation.

## Validation

The new regression fails on base `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with the fix.

```text
.................                                                        [100%]
17 passed in 0.26s
```

Changed Python files pass the repository F-rule lint gate.
