"""A BOM in config.json must not send `cow backup` at the wrong workspace.

``config.json`` is a file the docs tell users to edit by hand ("Add the
following to config.json"), and Windows Notepad and PowerShell save it with a
UTF-8 BOM. ``cli.commands.backup._read_config`` opens it as plain utf-8, so the
BOM makes ``json.load`` raise; the helper catches that and answers ``{}``.

Every caller then treats the install as unconfigured. ``_workspace_from_config``
falls back to ``~/cow``, so ``cow backup`` archives that directory instead of the
``agent_workspace`` the user configured -- the console prints a successful
archive of somewhere else, and the real workspace is not in it. ``restore`` hits
the same read on the copy inside the archive, where the failure is not caught at
all and aborts the restore.

``a9dfc54c`` ("tolerate UTF-8 BOM in config.json") fixed this read for the web
console and the CLI helper but not for the backup command.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli.commands import backup as cli_backup  # noqa: E402

CONFIG = {"agent_workspace": "", "model": "qwen-max", "web_password": "s3cret"}


def _write_config(data_root: Path, bom=True) -> Path:
    CONFIG["agent_workspace"] = str(data_root / "my-workspace")
    path = data_root / "config.json"
    path.write_text(
        json.dumps(CONFIG, ensure_ascii=False),
        encoding="utf-8-sig" if bom else "utf-8",
    )
    return path


def test_read_config_reads_a_bom_encoded_config(tmp_path):
    _write_config(tmp_path)

    assert cli_backup._read_config(tmp_path) == CONFIG, (
        "a config.json saved with a BOM must still be read"
    )


def test_backup_uses_the_configured_workspace(tmp_path):
    """The user-visible half: the archive must target the configured workspace."""
    _write_config(tmp_path)

    workspace = cli_backup._workspace_from_config(cli_backup._read_config(tmp_path))

    assert workspace == Path(CONFIG["agent_workspace"]), (
        "a BOM must not silently fall back to the default workspace"
    )


def test_a_bom_less_config_still_reads(tmp_path):
    """Control: the fix must not change behaviour for files without a BOM."""
    _write_config(tmp_path, bom=False)

    assert cli_backup._read_config(tmp_path) == CONFIG
