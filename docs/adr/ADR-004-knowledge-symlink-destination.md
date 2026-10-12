# ADR 004: fix(knowledge): validate resolved import destinations before writing

Status: Proposed

## Context

Knowledge imports validate their category but write the destination directly. An existing document symlink can therefore overwrite a file outside knowledge/. A dangling symlink also bypasses the current missing-path ancestor check in create_document.

## Decision

Validate the complete resolved candidate even when its target is missing, and apply that validation to every import destination, including conflict-renamed paths. Refuse escapes before modifying a file.

## Consequences

The change is confined to the affected contract and can be reverted independently. Existing behavior covered by the focused suite remains supported. No external API or model calls were used for validation.

## Validation

The new regression fails on base `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with the fix.

```text
.............................                                            [100%]
29 passed in 0.30s
```

Changed Python files pass the repository F-rule lint gate.
