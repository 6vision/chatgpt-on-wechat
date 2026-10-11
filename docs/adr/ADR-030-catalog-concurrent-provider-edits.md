# ADR 030: fix(models): serialize catalog edits and cache publication

Status: Accepted for this candidate.

## Context

Reading the catalog fresh before save does not protect the read-modify-write interval. Two provider edits can each read the same store and erase one another. A concurrent cache fill can also publish an old snapshot after a save invalidates the cache.

## Decision

Use one reentrant process lock around catalog transactions, cache loading, and invalidation. Keep entry validation outside the transaction and retain the existing atomic file writer.

## Consequences

Concurrent console edits preserve both providers and cache reads observe saves consistently within one CowAgent process. The lock does not claim cross-process transaction coordination.

## Validation

The focused regression fails on the unmodified base and passes with this change. tests/test_model_catalog_concurrent_edits.py tests/test_model_catalog_atomic_write.py tests/test_model_catalog_api.py passed locally; changed Python files passed CI-equivalent Ruff F checks. These are local native-contract checks using controlled doubles, not live provider or channel acceptance.
