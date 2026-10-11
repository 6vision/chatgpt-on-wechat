# ADR 021: fix(search): honor path globs in the Python fallback

## Context

Path-scoped file_glob patterns such as src/*.py and **/*.py work with ripgrep but are matched against only the basename in Python, yielding a successful empty result for existing source matches.

## Decision

Match slash-containing globs against root-relative path segments, supporting ** across zero or more directories; retain basename matching for simple file filters. Memoize the two-dimensional matching state so repeated recursive globs cannot expand exponentially.

## Consequences

Python fallback agrees with path-scoped filters and brace expansion. Single-segment wildcards do not traverse extra directories. Independent review exposed an exponential recursive-glob case in the first candidate; the frozen revision includes a bounded-state implementation and adversarial subprocess regression.

## Acceptance

The regression in `tests/test_cow32_search_path_glob.py` fails on `5f54fc5beb55e522091ebfbe3a11aece9bb7d502` and passes with this decision. Related existing tests must pass. Validation uses local fixtures without external services or model calls.
