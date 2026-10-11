# ADR 027: fix(telegram): keep link targets literal during Markdown rendering

Status: Accepted for this candidate.

## Context

The Telegram renderer creates anchor tags before running emphasis substitutions over the complete HTML. URL path segments such as __archive__ become bold tags inside href, corrupting the destination and Telegram parse mode.

## Decision

Park rendered links during the emphasis passes, apply formatting to labels, and restore links afterward. Use collision-safe placeholders so original text is not mistaken for a parked link.

## Consequences

Link destinations remain escaped literal URLs; label, surrounding emphasis, and inline code formatting continue to work.

## Validation

The focused regression fails on the unmodified base and passes with this change. tests/test_telegram_markdown_link_targets.py tests/test_telegram_markdown_fences.py passed locally; changed Python files passed CI-equivalent Ruff F checks. These are local native-contract checks using controlled doubles, not live provider or channel acceptance.
