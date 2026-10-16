"""A failed replacement cannot remove an already installed working skill."""

import errno
import io
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from agent.skills.manager import SkillManager
from agent.skills.service import SkillService


OLD = "---\nname: sample\ndescription: Existing skill\n---\n\n# Old instructions\n"
NEW = "---\nname: sample\ndescription: Updated skill\n---\n\n# New instructions\n"


@pytest.fixture
def installed(tmp_path, monkeypatch):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    custom = tmp_path / "skills"
    skill = custom / "sample"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(OLD, encoding="utf-8")
    (skill / "resource.txt").write_text("original resource", encoding="utf-8")
    manager = SkillManager(builtin_dir=str(builtin), custom_dir=str(custom))
    service = SkillService(manager)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("sample/SKILL.md", NEW)
        package.writestr("sample/resource.txt", "updated resource")

    def download(url, destination):
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        if url.endswith(".zip"):
            Path(destination).write_bytes(archive.getvalue())
        else:
            Path(destination).write_text(NEW, encoding="utf-8")

    monkeypatch.setattr(service, "_download_file", download)
    return service, skill, builtin, custom


def _payload(kind):
    return {
        "name": "sample", "type": kind,
        "files": [{"url": "https://fixture.invalid/skill.zip"}] if kind == "package"
        else [{"url": "https://fixture.invalid/SKILL.md", "path": "SKILL.md"}],
    }


def _assert_old_skill_reloads(skill, builtin, custom):
    assert (skill / "SKILL.md").read_text(encoding="utf-8") == OLD
    assert (skill / "resource.txt").read_text(encoding="utf-8") == "original resource"
    fresh = SkillManager(builtin_dir=str(builtin), custom_dir=str(custom))
    assert fresh.get_skill("sample").skill.description == "Existing skill"


def test_copy_failure_preserves_the_existing_installed_package(installed, monkeypatch):
    service, skill, builtin, custom = installed

    def disk_full(source, destination, *args, **kwargs):
        Path(destination).mkdir(parents=True)
        (Path(destination) / "partial.txt").write_text("partial copy")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(shutil, "copytree", disk_full)
    with pytest.raises(OSError, match="No space left"):
        service.add(_payload("package"))
    _assert_old_skill_reloads(skill, builtin, custom)


def test_url_promotion_failure_restores_the_previous_skill(installed, monkeypatch):
    service, skill, builtin, custom = installed
    rename = os.rename

    def fail_new_skill(source, destination, *args, **kwargs):
        marker = Path(source) / "SKILL.md"
        if Path(destination) == skill and marker.is_file() and marker.read_text(encoding="utf-8") == NEW:
            raise PermissionError("replacement unavailable")
        return rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", fail_new_skill)
    with pytest.raises(PermissionError, match="replacement unavailable"):
        service.add(_payload("url"))
    _assert_old_skill_reloads(skill, builtin, custom)


@pytest.mark.parametrize("kind", ["url", "package"])
def test_successful_update_replaces_the_skill_and_reloads_metadata(installed, kind):
    service, skill, builtin, custom = installed
    service.add(_payload(kind))
    assert (skill / "SKILL.md").read_text(encoding="utf-8") == NEW
    fresh = SkillManager(builtin_dir=str(builtin), custom_dir=str(custom))
    assert fresh.get_skill("sample").skill.description == "Updated skill"
    assert [p.name for p in custom.iterdir() if p.is_dir()] == ["sample"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_url_install_keeps_umask_permissions(installed):
    service, skill, _, _ = installed
    service.add(_payload("url"))
    umask = os.umask(0)
    os.umask(umask)
    assert skill.stat().st_mode & 0o777 == 0o777 & ~umask


@pytest.mark.parametrize("kind", ["local", "staged"])
def test_cli_copy_failure_keeps_the_previous_registered_skill(installed, tmp_path, monkeypatch, kind):
    from cli.commands import skill as skill_cli

    service, skill, builtin, custom = installed
    incoming = tmp_path / "incoming" / "sample"
    incoming.mkdir(parents=True)
    (incoming / "SKILL.md").write_text(NEW, encoding="utf-8")
    monkeypatch.setattr(skill_cli, "get_skills_dir", lambda agent_id=None: str(custom))
    original_config = (custom / "skills_config.json").read_bytes()

    def disk_full(source, destination, *args, **kwargs):
        Path(destination).mkdir(parents=True)
        (Path(destination) / "partial.txt").write_text("partial copy")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(shutil, "copytree", disk_full)
    with pytest.raises(OSError, match="No space left"):
        if kind == "local":
            skill_cli.install_skill(str(incoming))
        else:
            skill_cli.commit_staged(str(incoming.parent))
    assert (custom / "skills_config.json").read_bytes() == original_config
    _assert_old_skill_reloads(skill, builtin, custom)
