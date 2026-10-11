# ADR 003: fix(common): honor one deadline across token wait notifications

Status: Proposed

## Context

TokenBucket.get_token applies the full timeout after every condition notification. Contended callers or spurious notifications can extend a one-second request indefinitely without receiving a token.

## Decision

Compute a monotonic deadline once per request and pass only its remaining budget into each wait. Keep unlimited waits and shutdown signaling unchanged.

## Consequences

The change is confined to the affected contract and can be reverted independently. Existing behavior covered by the focused suite remains supported. No external API or model calls were used for validation.

## Validation

The new regression fails on base `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with the fix.

```text
.........                                                                [100%]
9 passed in 5.70s
```

Changed Python files pass the repository F-rule lint gate.
