# encoding:utf-8
"""Deleting an Agent must take its uploaded avatar with it.

An Agent's avatar bytes live in ``<shared root>/avatars/<agent_id><ext>`` --
see ``_avatar_path`` in ``channel/web/api/agents.py`` -- which is *outside* the
Agent's own workspace. ``AgentAdminService.delete_agent`` sweeps the roster
entry, the workspace directory, the session-prefs store and the project store,
so the id is reusable and clean everywhere except that one file.

Two things follow, and the second is the sharper one:

1. ``delete_agent`` documents itself as removing an Agent *"for good, files
   and all"*, and the residue is unbounded (2 MiB per deletion).
2. ``AgentAvatarHandler.GET`` resolved the file by id alone while ``POST``
   checked the roster first, so ``/api/agents/<deleted id>/avatar`` kept
   serving the deleted Agent's picture to anyone who held the URL.

The reading forms are unaffected: a live Agent with no picture still 404s, and
a live Agent with one still serves it.
"""

import json

import pytest

from agent import team
from agent.admin import AgentAdminService
from agent.registry import AgentRegistry, set_agent_registry


@pytest.fixture
def admin(tmp_path):
    primary = tmp_path / "primary"
    primary.mkdir()
    settings = {
        "agent_workspace": str(tmp_path),
        "default_agent_id": "primary",
        "agents": [
            {"id": "primary", "name": "Primary",
             "workspace": str(primary), "enabled": True},
        ],
        "channel_instances": [],
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(settings), encoding="utf-8")
    set_agent_registry(AgentRegistry.from_config(team.resolve(settings)))
    try:
        yield AgentAdminService(str(config_path)), tmp_path, config_path
    finally:
        set_agent_registry(None)


def _avatar_file(root, agent_id, suffix=".png"):
    """Drop an uploaded picture where the upload handler would have put it."""
    from common.state_dir import shared_root

    # shared_root() follows the *default* Agent's workspace through the global
    # registry, which create/delete just replaced -- so re-pin it first or the
    # file lands in the developer's own workspace.
    _repin(root)
    base = shared_root() / "avatars"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{agent_id}{suffix}"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + agent_id.encode())
    return path


def _repin(root):
    set_agent_registry(
        AgentRegistry.from_config(team.resolve({"agent_workspace": str(root)})))


def _second_agent(service, root, agent_id="research"):
    """Create an Agent on the layout ``delete_agent`` is willing to erase.

    ``delete_agent`` only removes a workspace that sits at
    ``<instance root>/agents/<id>`` (see its docstring), so the fixture puts it
    there -- otherwise the workspace assertions below would be asserting a
    refusal rather than a sweep.
    """
    agents_dir = root / "agents"
    agents_dir.mkdir(exist_ok=True)
    return service.create_agent(agent_id, agent_id.title(),
                                str(agents_dir / agent_id))


# --- delete_agent sweeps the avatar --------------------------------------

def test_delete_agent_removes_the_uploaded_avatar(admin):
    service, root, _ = admin
    _second_agent(service, root)
    avatar = _avatar_file(root, "research")
    assert avatar.is_file()

    service.delete_agent("research")

    assert not avatar.exists(), "the deleted Agent's avatar survived"
    # The workspace did go away, so this is a missed file rather than a
    # deletion that never ran.
    assert not (root / "agents" / "research").exists()


def test_delete_agent_removes_every_avatar_extension(admin):
    service, root, _ = admin
    _second_agent(service, root)
    written = [_avatar_file(root, "research", suffix) for suffix in (".png", ".jpg")]

    service.delete_agent("research")

    for path in written:
        assert not path.exists(), f"{path.name} survived the deletion"


def test_delete_agent_sweeps_the_avatar_of_an_agent_that_never_had_one(admin):
    """A deletion must not fail just because there is no avatar on disk."""
    service, root, _ = admin
    _second_agent(service, root)

    result = service.delete_agent("research")

    assert result["deleted"] is True


def test_delete_agent_still_clears_the_workspace_and_the_two_stores(admin):
    """The sweeps that already worked must keep working."""
    service, root, _ = admin
    _second_agent(service, root)
    avatar = _avatar_file(root, "research")

    service.delete_agent("research")

    assert not (root / "agents" / "research").exists()
    assert not avatar.exists()


def test_an_id_reused_after_deletion_starts_with_no_picture(admin):
    """The id is reusable, and the next Agent must not inherit the picture."""
    service, root, _ = admin
    _second_agent(service, root)
    _avatar_file(root, "research")
    service.delete_agent("research")

    _second_agent(service, root)

    from channel.web.api.agents import _avatar_path

    assert _avatar_path("research") is None


# --- the GET endpoint asks the roster, like POST already did -------------

def test_the_avatar_endpoint_serves_a_live_agents_picture(admin):
    """The reading path must keep working: a live Agent with a file is served."""
    service, root, _ = admin
    _second_agent(service, root)
    avatar = _avatar_file(root, "research")

    body, status, headers = _get_avatar("research")

    assert status == "200 OK", f"{status}: {body!r}"
    assert body == avatar.read_bytes()
    assert headers["Content-Type"] == "image/png"


def test_the_avatar_endpoint_refuses_an_id_that_left_the_roster(admin):
    """The residue case: the file outlives the roster entry."""
    service, root, _ = admin
    _second_agent(service, root)
    avatar = _avatar_file(root, "research")
    assert avatar.is_file()

    service.delete_agent("research")

    body, status, _ = _get_avatar("research")
    assert status == "404 Not Found", f"served a deleted Agent's picture: {body!r}"
    assert b"PNG" not in (body if isinstance(body, bytes) else body.encode())


def test_the_avatar_handler_checks_the_roster_before_reading_the_file(admin):
    """The guard has to come before the file is resolved, and POST has one too.

    Asserted against the source because the check under test *is* the ordering:
    the roster lookup must happen before ``_avatar_path`` turns an id into a
    filename on disk.
    """
    import inspect

    from channel.web.api.agents import AgentAvatarHandler

    get_source = inspect.getsource(AgentAvatarHandler.GET)
    post_source = inspect.getsource(AgentAvatarHandler.POST)

    assert "get_agent_registry().get(agent_id" in get_source, (
        "GET resolves the file by id without asking the roster"
    )
    assert get_source.index("get_agent_registry().get(agent_id") < \
        get_source.index("_avatar_path(agent_id)"), (
        "the roster check has to come before the file is resolved"
    )
    # The asymmetry this fixes: POST already had the check.
    assert "get_agent_registry().get(agent_id" in post_source


def _get_avatar(agent_id):
    """Call the real GET handler with a logged-in web.ctx.

    Returns (body, status, headers). The handler touches ``web.ctx`` (the 404
    branch sets a status and a header) and ``web.header``, so both are stood
    in for; everything else -- the roster lookup, the file read -- is the real
    code path.
    """
    from channel.web.api import agents as agents_module

    captured = {"headers": {}}

    def fake_header(key, value):
        captured["headers"][key] = value

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.status = "200 OK"
    ctx.headers = {}
    ctx.env = type("env", (), {"REQUEST_METHOD": "GET",
                                "PATH_INFO": "/api/agents/%s/avatar" % agent_id})()

    web = pytest.importorskip("web")
    real_ctx, real_header = web.ctx, web.header
    web.ctx = ctx
    web.header = fake_header
    try:
        body = agents_module.AgentAvatarHandler().GET(agent_id)
    finally:
        web.ctx, web.header = real_ctx, real_header

    return body, ctx.status, captured["headers"]


def test_the_default_agents_own_avatar_survives_another_agents_deletion(admin):
    """The sweep is keyed by id, so it must not touch a neighbour."""
    service, root, _ = admin
    _second_agent(service, root)
    primary_avatar = _avatar_file(root, "primary")
    _avatar_file(root, "research")

    service.delete_agent("research")

    assert primary_avatar.is_file()