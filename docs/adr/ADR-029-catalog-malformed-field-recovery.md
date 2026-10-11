# ADR 029: fix(models): recover malformed catalog provider fields independently

Status: Accepted for this candidate.

## Context

The catalog reader promises to heal damaged stored entries, but scalar overrides/hidden fields raise while iterating, string hidden fields turn into character tombstones, and infinite token limits raise uncaught OverflowError. One provider can take the entire models view down.

## Decision

Require list containers for overrides and tombstones, ignore unusable fields independently, and normalize nonfinite limits into the existing ValueError validation path.

## Consequences

Healthy provider entries and healthy fields survive hand-edited or damaged documents. Invalid fields are discarded consistently with the catalog healing contract.

## Validation

The focused regression fails on the unmodified base and passes with this change. tests/test_model_catalog_malformed_fields.py tests/test_model_catalog_atomic_write.py tests/test_model_catalog_api.py passed locally; changed Python files passed CI-equivalent Ruff F checks. These are local native-contract checks using controlled doubles, not live provider or channel acceptance.
