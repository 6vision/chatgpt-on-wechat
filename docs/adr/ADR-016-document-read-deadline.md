# ADR 016: fix(web-fetch): bound the whole document transfer time

## Context

Document downloads enforce only a socket inactivity timeout. A server that continually sends bytes can occupy a tool indefinitely, unlike the webpage read path with a whole-transfer deadline.

## Decision

Reuse save_response with the existing byte limit and whole-read budget, and report timeout or oversize failures while removing partial artifacts.

## Consequences

Slow trickle transfers stop within the documented budget after a streamed chunk. Downloads commit only once complete and retain existing document parsing.

## Acceptance

The regression in `tests/test_cow32_document_read_deadline.py` fails on `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with this decision. Related existing tests must pass. Validation uses local fixtures without external services or model calls.
