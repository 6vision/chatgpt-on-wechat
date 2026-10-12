# ADR 012: fix(write): preserve success when memory notification fails

## Context

Writing an indexed memory file commits the new contents, then reports an error if mark_dirty raises. The model can retry a write that already succeeded.

## Decision

Treat index notification as best effort after the file commit, matching the edit tool, and return a warning when indexing could not be notified.

## Consequences

The persisted file and reported outcome agree. The warning explains that retrieval may need a rescan; filesystem failures remain errors.

## Acceptance

The regression in `tests/test_cow32_write_memory_notify.py` fails on `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with this decision. Related existing tests must pass. Validation uses local fixtures without external services or model calls.
