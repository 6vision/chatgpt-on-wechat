# ADR 020: fix(search): skip special files before Python content reads

## Context

The Python fallback opens every small filesystem entry. A FIFO reports size zero but its open blocks waiting for a writer, defeating the search deadline and stranding the tool.

## Decision

Require a regular file before opening fallback content, following symlinks to inspect the actual target.

## Consequences

Regular source files and symlinks to them remain searchable. Pipes, devices, and sockets cannot block content searches.

## Acceptance

The regression in `tests/test_cow32_search_special_files.py` fails on `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with this decision. Related existing tests must pass. Validation uses local fixtures without external services or model calls.
