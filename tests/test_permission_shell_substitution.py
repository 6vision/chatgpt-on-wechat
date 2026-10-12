"""Shell substitutions must not smuggle a gated command past a bash mode."""
# encoding:utf-8

import pytest

from agent.permission import policy as policy_module
from agent.permission.policy import (
    READ_ONLY,
    WORKSPACE_WRITE,
    check_tool_call,
)


def _ro(command):
    """Verdict under read-only."""
    return "allow" if check_tool_call(READ_ONLY, "bash", {"command": command}).allowed else "deny"


def _ww(command, cwd, roots):
    """Verdict under workspace-write, with an explicit writable area."""
    decision = check_tool_call(
        WORKSPACE_WRITE,
        "bash",
        {"command": command},
        cwd=str(cwd),
        write_roots=[str(roots)],
    )
    return "allow" if decision.allowed else "deny"


# Commands that must be refused no matter how they are spelled.
BACKTICK_COMMANDS = [
    "echo `rm -rf x`",
    "echo `touch pwned.txt`",
    "echo `touch` `pwned.txt`",
    "echo `curl http://example.com/x`",
    "echo `chmod 777 /etc/passwd`",
    "echo `tee /etc/cron.d/evil`",
    "echo `dd if=/dev/zero of=out.bin`",
    "echo `sed -i s/a/b/ f`",
    "echo `truncate -s 0 f`",
]

PROCESS_SUBSTITUTION_COMMANDS = [
    "cat <(rm -rf x)",
    "cat <(touch pwned.txt)",
    "diff <(rm -rf x) y",
    "diff y <(touch pwned.txt)",
    "echo <(tee pwned.txt)",
    "cat <(dd if=/dev/zero of=out.bin)",
    "cat <(sed -i s/a/b/ f)",
    "cat <(truncate -s 0 f)",
    "diff <(chmod 777 /etc/passwd) /dev/null",
]


# --- read-only --------------------------------------------------------------


@pytest.mark.parametrize("command", BACKTICK_COMMANDS)
def test_backticks_cannot_hide_a_write_from_read_only(command):
    assert _ro(command) == "deny"


@pytest.mark.parametrize("command", PROCESS_SUBSTITUTION_COMMANDS)
def test_process_substitution_cannot_hide_a_write_from_read_only(command):
    assert _ro(command) == "deny"


@pytest.mark.parametrize(
    "substituted, spelled_out",
    [
        ("echo `rm -rf x`", "echo $(rm -rf x)"),
        ("echo `touch pwned.txt`", "echo $(touch pwned.txt)"),
        ("echo `tee /etc/cron.d/evil`", "echo $(tee /etc/cron.d/evil)"),
        ("cat <(rm -rf x)", "cat $(rm -rf x)"),
        ("cat <(touch pwned.txt)", "cat $(touch pwned.txt)"),
        ("diff <(rm -rf x) y", "diff $(rm -rf x) y"),
    ],
)
def test_both_spellings_now_get_the_same_verdict(substituted, spelled_out):
    # The control: the $( ) spelling is what the segmenter always understood.
    # A backquote or a process substitution must not be treated as safer.
    assert _ro(substituted) == _ro(spelled_out) == "deny"


def test_a_literal_backtick_is_still_a_literal():
    # Escaped, so the shell prints it rather than running anything.
    assert _ro(r"echo \`rm -rf x\`") == "allow"


def test_backticks_holding_only_a_read_are_fine():
    assert _ro("echo `date`") == "allow"
    assert _ro("echo `basename /a/b.txt`") == "allow"


def test_unbalanced_substitution_does_not_crash_the_gate():
    # Nothing to run, so there is nothing to refuse; the gate must still answer.
    assert _ro("echo `rm -rf x") in {"allow", "deny"}
    assert _ro("cat <(rm -rf x") in {"allow", "deny"}


# --- workspace-write --------------------------------------------------------
#
# Two things get in the way of using ``tmp_path`` here. ``_normalize_roots``
# deliberately adds ``tempfile.gettempdir()`` to every writable set, and
# ``tests/conftest.py`` points ``HOME``/``USERPROFILE`` at a directory inside
# it, so both ``tmp_path`` and ``Path.home()`` sit under temp and there is no
# "outside" to escape to. The fixture below redirects the trusted temp root
# instead, which keeps it writable for an unprivileged user on any platform.


@pytest.fixture
def area(monkeypatch, tmp_path):
    """A workspace with a sibling directory outside it, outside temp."""
    import tempfile

    # Redirect the trusted root instead of moving the workspace: an earlier
    # version anchored on the filesystem root, which is not writable for an
    # unprivileged user on Linux CI.
    fake_temp = tmp_path / "trusted"
    fake_temp.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fake_temp))

    base = tmp_path / "area"
    root = base / "ws"
    (root / "sub").mkdir(parents=True)
    (base / "outside").mkdir()
    # Guard the premise: if temp still covered the base, every case below would
    # pass for the wrong reason.
    assert policy_module.tempfile.gettempdir() not in str(base)
    yield base, root


@pytest.mark.parametrize(
    "command",
    [
        "echo `rm -rf ../outside`",
        "echo `touch ../outside/pwned.txt`",
        "echo `tee ../outside/pwned.txt`",
        "cat <(rm -rf ../outside)",
        "cat <(touch ../outside/pwned.txt)",
        "cat <(tee ../outside/pwned.txt)",
        "diff <(rm -rf ../outside) y",
    ],
)
def test_substitutions_cannot_write_outside_the_roots(command, area):
    _base, root = area
    assert _ww(command, root, root) == "deny"


def test_the_dollar_paren_spelling_was_already_refused_outside_the_roots(area):
    _base, root = area
    # The control for the cases above: $( ) was always caught here.
    assert _ww("echo $(rm -rf ../outside)", root, root) == "deny"
    assert _ww("cat $(rm -rf ../outside)", root, root) == "deny"


def test_a_write_inside_the_roots_stays_allowed(area):
    _base, root = area
    assert _ww("rm -rf sub", root, root) == "allow"
    assert _ww("echo `touch sub/inside.txt`", root, root) == "allow"
    assert _ww("cat <(touch sub/inside.txt)", root, root) == "allow"


def test_a_read_outside_the_roots_stays_allowed(area):
    _base, root = area
    assert _ww("cat ../outside/notes.txt", root, root) == "allow"
    assert _ww("echo `cat ../outside/notes.txt`", root, root) == "allow"


# --- the segmenter itself ---------------------------------------------------


def test_the_substituted_command_becomes_its_own_segment():
    from agent.permission.policy import _parse_segments

    segments = _parse_segments("echo `rm -rf x`")
    assert ["rm", "-rf", "x"] in segments

    segments = _parse_segments("cat <(tee out.txt)")
    assert ["tee", "out.txt"] in segments

    # A subshell is one segment already; substitution must not change that.
    assert _parse_segments("echo $(rm -rf x)") == [["echo", "$"], ["rm", "-rf", "x"]]


def test_a_parenthesis_inside_quotes_does_not_open_a_substitution():
    from agent.permission.policy import _parse_segments

    segments = _parse_segments("echo 'a <(b'")
    assert ["echo", "a <(b"] in segments


def test_nested_substitutions_are_classified():
    from agent.permission.policy import _parse_segments

    segments = _parse_segments("echo <(`rm -rf x`)")
    assert ["rm", "-rf", "x"] in segments
    assert _ro("echo <(`rm -rf x`)") == "deny"


def test_the_placeholder_is_not_readable_as_a_command_or_a_path():
    # The outer command receives a marker where the substitution was. If it
    # ever looked like a command name or a path, a gate could act on it.
    from agent.permission.policy import _parse_segments

    segments = _parse_segments("cat <(echo hi)")
    outer = [segment for segment in segments if segment[0] == "cat"]
    assert outer and all("\x00" not in token for token in outer[0][:1])

@pytest.mark.parametrize("command", ["cat <(rm -rf x ')", "echo `rm x '`"])
def test_an_unlexable_substitution_fails_closed(command):
    assert not check_tool_call(READ_ONLY, "bash", {"command": command}).allowed
