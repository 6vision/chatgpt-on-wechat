"""read-only mode must find the git sub-command after git's global options."""
import pytest

from agent.permission.policy import READ_ONLY, check_tool_call


def _check(command):
    return check_tool_call(READ_ONLY, "bash", {"command": command})


@pytest.mark.parametrize("command", [
    "git -C /srv/app status",
    "git -C/srv/app status",
    "git -c core.pager=cat log --oneline",
    "git -ccore.pager=cat log",
    "git --git-dir /srv/app/.git log",
    "git --git-dir=/srv/app/.git log",
    "git --work-tree /srv/app status",
    "git --work-tree=/srv/app status",
    "git --namespace ns log",
    "git --namespace=ns log",
    "git --exec-path status",
    "git --exec-path=/usr/lib/git-core status",
    "git --no-pager -C /srv/app -c color.ui=never diff",
    "git -C /srv/app log -C",
])
def test_global_option_before_read_subcommand_is_allowed(command):
    decision = _check(command)
    assert decision.allowed, decision.reason


@pytest.mark.parametrize("command,sub", [
    ("git -C /srv/app push", "push"),
    ("git -c user.name=x commit -m msg", "commit"),
    ("git --git-dir=/srv/app/.git checkout main", "checkout"),
])
def test_global_option_before_write_subcommand_names_the_subcommand(command, sub):
    decision = _check(command)
    assert not decision.allowed
    assert f"'git {sub}'" in decision.reason


def test_dash_c_is_not_a_write_flag_of_a_read_subcommand():
    assert _check("git -C /srv/app log").allowed
    assert _check("git log -C").allowed


def test_write_flags_still_refused_after_global_options():
    assert not _check("git -C /srv/app branch -D topic").allowed


def test_branch_copy_flags_are_still_refused():
    assert not _check("git branch -c old new").allowed
    assert not _check("git -C /srv/app branch -C old new").allowed
    assert not _check("git branch --copy old new").allowed
