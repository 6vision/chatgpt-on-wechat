# encoding:utf-8
"""Read-only mode must not let a git write through.

``agent/permission/policy.py`` decides whether a ``bash`` call may run under
``read-only``, and the git classifier is the part that has to be right. The
allowlist holds sub-commands that only read *in their list form*, and a
sub-command handed a name to create looks exactly like a read unless the
operands are inspected: ``git tag v1`` and ``git branch topic`` both write a
ref while carrying no write flag at all.

This was the module's first coverage -- nothing imported
``agent.permission.policy`` before this file.
"""

import pytest

from agent.permission.policy import READ_ONLY, check_tool_call


def _verdict(command):
    return "allow" if check_tool_call(READ_ONLY, "bash", {"command": command}).allowed else "deny"


READ_ONLY_GIT_COMMANDS = [
    # inspecting
    "git status",
    "git log --oneline -5",
    "git diff HEAD~1",
    "git show abc123",
    "git reflog",
    "git describe --tags",
    "git blame app.py",
    "git config --get user.name",
    "git config --list",
    # branch / tag: read-only only while listing
    "git branch",
    "git branch -a",
    "git branch -r",
    "git branch -v",
    "git branch -i",
    "git branch --list",
    "git branch --contains abc123",
    "git branch --merged main",
    "git tag",
    "git tag -l",
    "git tag --list",
    "git tag -l 'v*'",
    "git tag --contains abc123",
    # remotes: read-only without a write verb
    "git remote",
    "git remote -v",
    "git remote show origin",
    "git remote get-url origin",
    # symbolic-ref reads with a single operand
    "git symbolic-ref HEAD",
    "git symbolic-ref --short HEAD",
    "git symbolic-ref refs/heads/main",
    # the list-only sub-commands this mirrors
    "git stash list",
    "git worktree list",
    "git notes list",
]

WRITE_GIT_COMMANDS = [
    # `git tag <name>` and `git branch <name>` create a ref. Note that `-a`
    # annotates a tag, so it is not the listing `-a` that `git branch -a` uses.
    "git tag v1.0.0",
    "git tag -a v1 -m msg",
    "git branch topic",
    "git branch new old",
    # remotes
    "git remote add origin https://example.com/x.git",
    "git remote set-url origin https://example.com/y.git",
    "git remote remove origin",
    "git remote rm origin",
    "git remote rename old new",
    "git remote prune origin",
    "git remote set-head origin -a",
    "git remote update",
    # a second operand makes symbolic-ref SET the ref, not read it
    "git symbolic-ref HEAD refs/heads/main",
    "git symbolic-ref refs/heads/main refs/heads/other",
]

# Refused before this change too, kept so the new guards cannot loosen them.
ALREADY_REFUSED_GIT_COMMANDS = [
    "git commit -m x",
    "git push origin main",
    "git branch -d topic",
    "git tag -d v1.0.0",
    "git stash pop",
    "git config user.name x",
    "git reset --hard",
]


@pytest.mark.parametrize("command", READ_ONLY_GIT_COMMANDS)
def test_read_only_git_listing_is_allowed(command):
    assert _verdict(command) == "allow", f"read-only mode refused a read: {command}"


@pytest.mark.parametrize("command", WRITE_GIT_COMMANDS)
def test_read_only_git_writes_are_refused(command):
    decision = check_tool_call(READ_ONLY, "bash", {"command": command})
    assert not decision.allowed, f"read-only mode let a write through: {command}"
    assert READ_ONLY in decision.reason


@pytest.mark.parametrize("command", ALREADY_REFUSED_GIT_COMMANDS)
def test_read_only_still_refuses_the_rest_of_git(command):
    assert _verdict(command) == "deny"
