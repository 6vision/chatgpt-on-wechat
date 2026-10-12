# ADR 015: fix(web-fetch): preserve literal text responses without HTML parsing

## Context

Extensionless text/plain responses are processed as HTML. Fetching source text such as <item> or literal entities silently discards or rewrites data.

## Decision

Keep decoded text/plain and JSON responses verbatim; continue extracting readable HTML for HTML or unknown response types.

## Consequences

Plain response whitespace, angle brackets, and entities survive retrieval. HTML extraction continues unchanged.

## Acceptance

The regression in `tests/test_cow32_webpage_plain_text.py` fails on `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with this decision. Related existing tests must pass. Validation uses local fixtures without external services or model calls.
