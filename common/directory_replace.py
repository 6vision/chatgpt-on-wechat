"""Replace a directory without discarding it before the new copy is ready."""

import os
import shutil
import tempfile

from common.log import logger

def replace_directory(source: str, target: str, move_source: bool = False) -> None:
    source = os.path.realpath(source)
    target = os.path.abspath(target)
    real_target = os.path.realpath(target)
    try:
        shared = os.path.commonpath([os.path.normcase(source), os.path.normcase(real_target)])
    except ValueError:
        shared = None
    if shared in (os.path.normcase(source), os.path.normcase(real_target)):
        raise ValueError("source and target directories overlap")
    _replace(source, target, move_source)


def _replace(source: str, target: str, move_source: bool) -> None:
    # rmtree previously refused a target symlink. Keep that boundary so a
    # planted skill-directory alias cannot replace an unrelated directory.
    if os.path.islink(target):
        raise OSError("cannot replace a directory symlink")
    if os.path.exists(target) and not os.path.isdir(target):
        raise NotADirectoryError(target)
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    stage_root = tempfile.mkdtemp(prefix=f".{os.path.basename(target)}.replace-", dir=parent)
    staged = os.path.join(stage_root, "new")
    backup = os.path.join(stage_root, "previous")
    retain_backup = False
    try:
        if move_source:
            os.rename(source, staged)
        else:
            shutil.copytree(source, staged)
        if os.path.exists(target):
            os.rename(target, backup)
        try:
            os.rename(staged, target)
        except BaseException:
            if os.path.exists(backup):
                try:
                    os.rename(backup, target)
                except BaseException:
                    retain_backup = True
                    logger.error(f"[DirectoryReplace] Could not restore directory; backup retained at {backup}")
            # Re-raise the original promotion failure even if restoring the
            # previous directory also failed; its backup remains recoverable.
            raise
    finally:
        if not retain_backup:
            shutil.rmtree(stage_root, ignore_errors=True)
