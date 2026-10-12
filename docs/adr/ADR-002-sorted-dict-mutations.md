# ADR 002: fix(common): keep sorted mappings consistent after bulk mutations

Status: Proposed

## Context

SortedDict underpins plugin priority order, but inherited dict clear, update, pop and setdefault bypass its heap. A clear followed by insertion leaves deleted plugin names in iteration, while update omits new plugins from dispatch order.

## Decision

Route mapping mutators through the existing heap-aware set/delete operations, clear both stores together, and expose values in the same order as keys and items.

## Consequences

The change is confined to the affected contract and can be reverted independently. Existing behavior covered by the focused suite remains supported. No external API or model calls were used for validation.

## Validation

The new regression fails on base `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with the fix.

```text
................                                                         [100%]
16 passed in 0.38s
```

Changed Python files pass the repository F-rule lint gate.
