# ADR 032: fix(minimax): align retained sessions with the chat completions schema

Status: Accepted for this candidate.

## Context

MinimaxBot.reply_text sends session.messages directly to /chat/completions, but MinimaxSession still emits legacy sender_type/sender_name/text dictionaries and never initializes the system prompt. Prompt reset creates a mixed schema and legacy token counting then raises on that system item.

## Decision

Use the shared Session role/content messages and initialize its system prompt. Update MiniMax trimming and length estimation to the same schema sent to the current endpoint.

## Consequences

Legacy reply sessions use one consistent schema, retain configured prompts, and trim old turns while preserving the latest query. Agent tool-calling message conversion is unaffected.

## Validation

The focused regression fails on the unmodified base and passes with this change. tests/test_minimax_session_chat_schema.py tests/test_minimax_provider.py::TestMinimaxConst tests/test_minimax_provider.py::TestMinimaxBotDefaultModel passed locally; changed Python files passed CI-equivalent Ruff F checks. These are local native-contract checks using controlled doubles, not live provider or channel acceptance.
