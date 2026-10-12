"""MiniMax's current endpoint consumes Chat-Completions-shaped sessions."""
from unittest.mock import Mock

from models.minimax.minimax_session import MinimaxSession
from models.session_manager import SessionManager


def test_initial_session_and_turns_use_role_content():
    session = MinimaxSession("chat", system_prompt="Be concise")
    session.add_query("hello")
    session.add_reply("hi")
    assert session.messages == [
        {"role": "system", "content": "Be concise"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    assert session.calc_tokens() == len("Be concisehellohi")


def test_session_manager_prompt_reset_keeps_the_same_message_schema():
    manager = SessionManager(MinimaxSession)
    session = manager.build_session("chat", system_prompt="old")
    session.add_query("discard")
    session = manager.build_session("chat", system_prompt="new")
    session.add_query("keep")
    assert session.messages == [
        {"role": "system", "content": "new"}, {"role": "user", "content": "keep"}]
    assert session.calc_tokens() == 7


def test_trimming_preserves_system_prompt_and_latest_query():
    session = MinimaxSession("chat", system_prompt="S")
    session.add_query("old user")
    session.add_reply("old reply")
    session.add_query("new")
    assert session.discard_exceeding(4) == 4
    assert session.messages == [{"role": "system", "content": "S"}, {"role": "user", "content": "new"}]


def test_native_reply_http_body_uses_the_current_endpoint_schema(monkeypatch):
    from models.minimax import minimax_bot

    monkeypatch.setattr(minimax_bot, "conf", lambda: {"minimax_api_key": "test-key", "minimax_api_base": "https://test.invalid/v1"})
    response = Mock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": "hi"}}],
                                 "usage": {"total_tokens": 4, "completion_tokens": 2}}
    post = Mock(return_value=response)
    monkeypatch.setattr(minimax_bot.requests, "post", post)
    bot = minimax_bot.MinimaxBot()
    session = bot.sessions.build_session("chat", system_prompt="S")
    session.add_query("hello")
    assert bot.reply_text(session)["content"] == "hi"
    assert post.call_args.args[0].endswith("/chat/completions")
    assert post.call_args.kwargs["json"]["messages"] == [
        {"role": "system", "content": "S"}, {"role": "user", "content": "hello"}]
