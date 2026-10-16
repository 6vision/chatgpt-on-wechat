"""LinkAI admin commands in groups must match the sender against the admin ids exactly.

``Util.is_admin`` tested ``actual_user_id in admin_user`` for each configured id, which
is a substring test on strings: a group member whose id is a fragment of an admin's id
(``wxid`` of ``wxid_admin_9f3a``) was treated as an admin and could toggle LinkAI,
summary and Midjourney settings. The private-chat branch and godcmd compare exactly.
"""
from types import SimpleNamespace

import pytest

import plugins

# plugins/linkai/__init__.py also imports the registered plugin, which refuses to
# load without a plugin path -- same idiom as test_linkai_summary_file.py.
plugins.instance.current_plugin_path = "./plugins/linkai"
from plugins.linkai.utils import Util  # noqa: E402
plugins.instance.current_plugin_path = None

from config import global_config  # noqa: E402


class _Context(dict):
    kwargs = {}


def _group_event(actual_user_id):
    context = _Context(isgroup=True)
    context.kwargs = {"msg": SimpleNamespace(actual_user_id=actual_user_id)}
    return {"context": context}


@pytest.fixture(autouse=True)
def _admins(monkeypatch):
    monkeypatch.setitem(global_config, "admin_users", ["wxid_admin_9f3a"])


def test_exact_admin_id_is_accepted():
    assert Util.is_admin(_group_event("wxid_admin_9f3a")) is True


@pytest.mark.parametrize("fragment", ["wxid", "admin", "9f3a", "wxid_admin"])
def test_fragment_of_an_admin_id_is_rejected(fragment):
    assert Util.is_admin(_group_event(fragment)) is False


@pytest.mark.parametrize("missing", [None, ""])
def test_missing_sender_id_is_rejected(missing):
    assert Util.is_admin(_group_event(missing)) is False
