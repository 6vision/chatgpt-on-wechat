from collections import defaultdict
from types import SimpleNamespace

import pytest

from bridge.agent_bridge import AgentBridge
from channel.wechatmp import wechatmp_channel

OPENID = "oUser_abc123"
DEFAULT_AGENT_ID = "primary"
OTHER_AGENT_ID = "team-a"


def make_channel():
    channel = wechatmp_channel.WechatMPChannel.__wrapped__.__new__(
        wechatmp_channel.WechatMPChannel.__wrapped__
    )
    channel.passive_reply = True
    channel.cache_dict = defaultdict(list)
    channel.running = {OPENID}
    return channel


def make_context(agent_id):
    return {
        "session_id": OPENID,
        "receiver": OPENID,
        "agent_id": agent_id,
        "msg": SimpleNamespace(msg_id="m1", from_user_id=OPENID),
    }


def queue_key(agent_id):
    # The key chat_channel.produce() files the turn under, and therefore the
    # session_id the worker callbacks are invoked with.
    return AgentBridge._cancel_key(agent_id, OPENID, DEFAULT_AGENT_ID)


def run_success(channel, agent_id):
    channel._success_callback(queue_key(agent_id), make_context(agent_id))


def run_fail(channel, agent_id):
    channel._fail_callback(
        queue_key(agent_id), RuntimeError("boom"), make_context(agent_id)
    )


@pytest.mark.parametrize("agent_id", [DEFAULT_AGENT_ID, OTHER_AGENT_ID])
def test_success_callback_clears_running(agent_id):
    channel = make_channel()

    run_success(channel, agent_id)

    assert OPENID not in channel.running


@pytest.mark.parametrize("agent_id", [DEFAULT_AGENT_ID, OTHER_AGENT_ID])
def test_fail_callback_clears_running(agent_id):
    channel = make_channel()

    run_fail(channel, agent_id)

    assert OPENID not in channel.running


@pytest.mark.parametrize("agent_id", [DEFAULT_AGENT_ID, OTHER_AGENT_ID])
def test_fail_callback_clears_running_when_reply_is_still_cached(agent_id):
    channel = make_channel()
    channel.cache_dict[OPENID].append(("text", "undrained"))

    run_fail(channel, agent_id)

    assert OPENID not in channel.running
