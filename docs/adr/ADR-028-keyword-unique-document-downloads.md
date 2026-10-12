# ADR 028: fix(keyword): retain distinct downloaded document replies

Status: Accepted for this candidate.

## Context

Every keyword document download is saved as tmp/<remote-basename>. Two different URLs ending in report.pdf overwrite the same file before queued replies send it, so an earlier reply delivers the later document.

## Decision

Allocate a fresh managed temporary directory for each successful download, preserving the original basename used for outgoing display.

## Consequences

Sequential and concurrent replies keep their own bytes and filenames. The files remain inside the existing managed tmp area; failed downloads create no staging directory.

## Validation

The focused regression fails on the unmodified base and passes with this change. tests/test_keyword_unique_document_downloads.py tests/test_keyword_attachment_urls.py passed locally; changed Python files passed CI-equivalent Ruff F checks. These are local native-contract checks using controlled doubles, not live provider or channel acceptance.
