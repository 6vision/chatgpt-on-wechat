# encoding:utf-8
"""A blank message must not kill the turn inside the role or dungeon handler.

``str.split(maxsplit=1)`` returns ``[]`` for an empty or whitespace-only string,
so reading ``clist[0]`` raises ``IndexError`` -- in ``plugins/role/role.py:141``
and in ``plugins/dungeon/dungeon.py:76``. Nothing on the way out handles it:
``PluginManager.emit_event`` calls the handler directly, ``channel/chat_channel.py``
does not wrap it, and the worker's failure callback only logs. An accidental
enter, or a WeChat text bubble with no body, therefore produces no reply of any
kind and the turn dies before the model is even called. ROLE is enabled by
default; DUNGEON is opt-in and carries the identical bug.

A blank message is not a command, so it should be treated exactly like any other
message that matches nothing. The assertions below pin that by comparing a blank
message against ordinary text, rather than only asserting "no exception" -- the
handler must not start answering blanks with an error of its own either.
"""

from unittest.mock import patch

import pytest

import plugins
from bridge.context import Context, ContextType
from common import const
from plugins import Event, EventAction, EventContext

# ``@plugins.register`` reads the importing plugin's path off the plugin
# instance, so it has to be pointed at each plugin's directory before the import.
plugins.instance.current_plugin_path = "./plugins/role"
from plugins.role import role as role_module  # noqa: E402

plugins.instance.current_plugin_path = "./plugins/dungeon"
from plugins.dungeon import dungeon as dungeon_module  # noqa: E402

plugins.instance.current_plugin_path = None

# The decorator hands the class to the plugin manager and binds nothing back,
# so the module attribute is None and the registered class has to be taken from
# the manager the same way the runtime does.
Role = plugins.instance.plugins["ROLE"]
Dungeon = plugins.instance.plugins["DUNGEON"]

# Both plugins split the same way, so every one of these produces an empty clist.
BLANKS = ["", " ", "\n", "\t", "  \n\t "]

BOTH_PLUGINS = [
    pytest.param(Role, role_module, id="role"),
    pytest.param(Dungeon, dungeon_module, id="dungeon"),
]


class FakeSessions:
    def __init__(self):
        self.system_prompts = {}

    def build_session(self, session_id, system_prompt=None):
        self.system_prompts[session_id] = system_prompt

    def clear_session(self, session_id):
        self.system_prompts.pop(session_id, None)


class FakeBot:
    def __init__(self):
        self.sessions = FakeSessions()


class FakeBridge:
    """Stands in for the bot bridge so the command parser is reached at all."""

    _bot = FakeBot()

    def __init__(self, *args, **kwargs):
        pass

    def get_bot_type(self, bot_role):
        return const.OPENAI

    def get_bot(self, bot_role):
        return FakeBridge._bot


def _handled(plugin_cls, module, content, plugin=None):
    """One handler call, with the stubs in place for the whole of it.

    conf() is read inside on_handle_context and by Dungeon's __init__, so the
    construction stays inside the patch too and the stub always reaches the
    plugin. Passing an existing ``plugin`` keeps its state between calls, which
    is what the mid-adventure case needs.
    """
    context = Context(ContextType.TEXT, content)
    context["session_id"] = "s1"
    event = EventContext(
        Event.ON_HANDLE_CONTEXT, {"context": context, "reply": None}
    )
    with patch.object(module, "conf", lambda: {"plugin_trigger_prefix": "$"}), \
            patch.object(module, "Bridge", FakeBridge):
        (plugin if plugin is not None else plugin_cls()).on_handle_context(event)
    return event


def _decisions(event):
    """What the handler decided, independent of the text it was handed."""
    return (event["reply"], event.action, "generate_breaked_by" in event["context"])


@pytest.mark.parametrize("blank", BLANKS)
@pytest.mark.parametrize("plugin_cls,module", BOTH_PLUGINS)
def test_a_blank_message_raises_nothing_and_answers_nothing(blank, plugin_cls, module):
    # Before the fix this raised IndexError out of the handler, so the turn was
    # over with no reply and the user saw nothing at all.
    event = _handled(plugin_cls, module, blank)

    assert event["reply"] is None
    assert event.action is EventAction.CONTINUE
    assert event["context"].content == blank


@pytest.mark.parametrize("blank", BLANKS)
@pytest.mark.parametrize("plugin_cls,module", BOTH_PLUGINS)
def test_a_blank_message_is_handled_like_any_other_unmatched_message(blank, plugin_cls, module):
    # The reference outcome: ordinary text, which matches no command either. A
    # blank has to be indistinguishable from it -- that is the whole contract,
    # and it rules out "fixing" the IndexError with an error reply of its own.
    expected = _decisions(_handled(plugin_cls, module, "hello"))

    assert _decisions(_handled(plugin_cls, module, blank)) == expected


def test_a_blank_message_mid_adventure_does_not_advance_the_story():
    # The case that matters most: a game is running, so the handler is on the
    # `or sessionid in self.games` branch and StoryTeller.action() indexes
    # user_action[-1] -- an empty string would raise there too. The blank has to
    # be dropped before any of that.
    dungeon = Dungeon()
    _handled(Dungeon, dungeon_module, "$开始冒险", plugin=dungeon)
    assert "s1" in dungeon.games

    event = _handled(Dungeon, dungeon_module, " ", plugin=dungeon)

    assert event["reply"] is None
    assert event["context"].content == " "
    assert dungeon.games["s1"].first_interact is True


def test_the_sibling_customize_guard_still_answers():
    # The $设定扮演 clist[1] fix has to survive this change: a blank must not
    # start short-circuiting commands that legitimately split to one element.
    event = _handled(Role, role_module, "$设定扮演")

    assert event["reply"] is not None
    assert "使用方法" in event["reply"].content


def test_a_real_command_is_still_matched():
    # And the commands themselves must be unaffected by the new early return.
    event = _handled(Role, role_module, "$角色")

    assert event["reply"] is not None
    assert "使用方法" in event["reply"].content
