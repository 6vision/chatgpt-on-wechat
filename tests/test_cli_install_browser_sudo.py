# encoding:utf-8
"""`cow install-browser` must not require a `sudo` binary to exist.

A container is usually root already and ships no `sudo` at all, so the
hard-coded `["sudo", "apt-get", ...]` made the whole installer abort with an
unhandled FileNotFoundError. The apt helper may only escalate when it is not
root and sudo is actually present.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli.commands import install


def test_root_does_not_prefix_sudo(monkeypatch):
    calls = []
    monkeypatch.setattr(install.os, "geteuid", lambda: 0)
    monkeypatch.setattr(install.subprocess, "call", lambda cmd, **kw: calls.append(cmd) or 0)

    assert install._apt_install("fonts-wqy-zenhei") == 0
    assert calls == [["apt-get", "install", "-y", "--no-install-recommends", "fonts-wqy-zenhei"]]


def test_non_root_with_sudo_prefixes(monkeypatch):
    calls = []
    monkeypatch.setattr(install.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(install.shutil, "which", lambda name: "/usr/bin/sudo")
    monkeypatch.setattr(install.subprocess, "call", lambda cmd, **kw: calls.append(cmd) or 0)

    assert install._apt_install("fonts-wqy-zenhei") == 0
    assert calls[0][:2] == ["sudo", "apt-get"]


def test_non_root_without_sudo_skips(monkeypatch):
    calls = []
    monkeypatch.setattr(install.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(install.shutil, "which", lambda name: None)
    monkeypatch.setattr(install.subprocess, "call", lambda cmd, **kw: calls.append(cmd) or 0)

    assert install._apt_install("fonts-wqy-zenhei") == 1
    assert calls == []
