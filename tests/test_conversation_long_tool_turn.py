import pytest
from agent.memory.conversation_store import ConversationStore

def tool_results(count):
    return [{'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': str(i), 'content': 'ok'}]} for i in range(count)]

@pytest.mark.parametrize('count', [21, 51, 101])
def test_answer_pairing_retains_original_query_after_tools(tmp_path, count):
    store = ConversationStore(tmp_path / 'messages.db')
    store.append_messages('session', [{'role': 'user', 'content': 'Build my report'}])
    expected_user = store.latest_seq('session')
    store.append_messages('session', tool_results(count))
    store.append_messages('session', [{'role': 'assistant', 'content': 'Report complete'}])
    assert store.get_latest_pair_seqs('session')['user_seq'] == expected_user
    assert store.get_latest_pair_seqs('session')['bot_seq'] == store.latest_seq('session')

@pytest.mark.parametrize('count', [51, 101])
def test_artifact_navigation_retains_originating_turn(tmp_path, count):
    store = ConversationStore(tmp_path / 'messages.db')
    store.append_messages('session', [{'role': 'user', 'content': 'Build my report'}])
    expected_user = store.latest_seq('session')
    store.append_messages('session', tool_results(count))
    store.record_artifacts('session', [{'path': str(tmp_path / 'report.md'), 'kind': 'markdown'}])
    assert store.list_artifacts()['items'][0]['turn_seq'] == expected_user

def test_tool_only_session_has_no_invented_origin(tmp_path):
    store = ConversationStore(tmp_path / 'messages.db')
    store.append_messages('session', tool_results(51))
    store.record_artifacts('session', [{'path': str(tmp_path / 'report.md'), 'kind': 'markdown'}])
    assert store.get_latest_pair_seqs('session')['user_seq'] is None
    assert store.list_artifacts()['items'][0]['turn_seq'] is None
