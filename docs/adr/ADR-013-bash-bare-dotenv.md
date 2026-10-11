# ADR 013: fix(bash): skip dotenv entries without values

## Context

A valid dotenv line containing only a key is parsed as None. Injecting it into the subprocess environment makes every shell command fail with a TypeError.

## Decision

Forward only assigned dotenv values, retaining an inherited environment value when the dotenv entry has no assignment.

## Consequences

Empty assigned values remain valid and override inheritance. Bare declarations no longer prevent command execution.

## Acceptance

The regression in `tests/test_cow32_bash_bare_dotenv.py` fails on `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with this decision. Related existing tests must pass. Validation uses local fixtures without external services or model calls.
