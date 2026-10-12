# ADR 014: fix(web-fetch): tolerate malformed document length headers

## Context

A document server with a malformed Content-Length header can deliver a valid body, but the document fetch path rejects it before reading. The webpage path already tolerates the same header.

## Decision

Use the existing nonnegative Content-Length parser for documents, retaining the streaming byte limit as the authoritative bound.

## Consequences

Malformed and absent lengths no longer reject readable documents; oversized declared and streamed bodies remain bounded.

## Acceptance

The regression in `tests/test_cow32_document_content_length.py` fails on `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with this decision. Related existing tests must pass. Validation uses local fixtures without external services or model calls.
