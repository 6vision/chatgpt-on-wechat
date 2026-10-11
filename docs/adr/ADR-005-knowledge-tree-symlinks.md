# ADR 005: fix(knowledge): exclude symlink children from tree traversal

Status: Proposed

## Context

The knowledge tree recursively follows directory symlinks. A link back to its parent repeats documents until the filesystem symlink limit intervenes, inflating page counts and nesting duplicate categories. Links to external folders expose titles and sizes of documents that read_file correctly refuses.

## Decision

Skip symlink children when scanning the knowledge tree. The configured knowledge root still resolves normally, and ordinary nested categories remain visible.

## Consequences

The change is confined to the affected contract and can be reverted independently. Existing behavior covered by the focused suite remains supported. No external API or model calls were used for validation. The listing omits all symlink children, including valid aliases to internal files or categories. A configured symlink knowledge root still resolves normally. Direct reads retain their existing resolved-path validation and can read internal aliases.

## Validation

The new regression fails on base `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with the fix.

```text
............................                                             [100%]
28 passed in 0.28s
```

Changed Python files pass the repository F-rule lint gate.
