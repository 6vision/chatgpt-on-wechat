# ADR 001: fix(common): reject UTF-8 split budgets that cannot make progress

Status: Proposed

## Context

A reply containing a multibyte character can make split_string_by_utf8_length loop forever when the byte budget is smaller than that character. Zero and negative budgets also cannot advance the cursor.

## Decision

Reject nonpositive budgets and reject a boundary that cannot fit the next complete codepoint. Normal splits still preserve every character and obey the byte limit.

## Consequences

The change is confined to the affected contract and can be reverted independently. Existing behavior covered by the focused suite remains supported. No external API or model calls were used for validation.

## Validation

The new regression fails on base `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with the fix.

```text
.......                                                                  [100%]
7 passed in 0.15s
```

Changed Python files pass the repository F-rule lint gate.
