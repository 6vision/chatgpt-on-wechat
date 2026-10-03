# encoding:utf-8
"""
Tests that the bash safety scanner recognises rm's recursive/force flags.

Defect: the scanner folded "recursive" and "force" into a single `has_rf`
flag that only a *combined* short flag could set, `--recursive` was skipped
with `continue` without setting any state, and every unrecognised flag token
hit the final `else: break`. So the scan abandoned the flag list before the
operand it exists to inspect.

User-visible consequence: with safety_mode on (the default) `rm -r -f /`,
`rm --recursive -f /`, `rm -f -r /` and `rm -rf --preserve-root /` produced no
warning, so Bash.execute ran them instead of stopping with the "delete the
entire filesystem" confirmation prompt.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.bash.bash import Bash

DESTROY_ROOT = "This command will delete the entire filesystem"


def warning_for(command):
    """Return the safety warning the scanner produces for `command`."""
    return Bash._get_safety_warning(None, command)


class TestRmFlagsReachOperand(unittest.TestCase):
    """Recursive plus force, however spelled, must still reach the `/` operand."""

    def test_combined_short_flag(self):
        """`rm -rf /` is the baseline the scanner was written for."""
        self.assertEqual(warning_for("rm -rf /"), DESTROY_ROOT)

    def test_combined_short_flag_glob_root(self):
        """`rm -rf /*` destroys the filesystem just as thoroughly."""
        self.assertEqual(warning_for("rm -rf /*"), DESTROY_ROOT)

    def test_separate_short_flags_recursive_first(self):
        """`rm -r -f /` is the same command as `rm -rf /`."""
        self.assertEqual(warning_for("rm -r -f /"), DESTROY_ROOT)

    def test_separate_short_flags_force_first(self):
        """Flag order does not change what the command does."""
        self.assertEqual(warning_for("rm -f -r /"), DESTROY_ROOT)

    def test_separated_long_flags(self):
        """The long spellings of the same flags must warn."""
        self.assertEqual(warning_for("rm --recursive --force /"), DESTROY_ROOT)

    def test_long_recursive_with_short_force(self):
        """`--recursive` must be recognised, not skipped without setting state."""
        self.assertEqual(warning_for("rm --recursive -f /"), DESTROY_ROOT)

    def test_unknown_long_flag_does_not_abort_scan(self):
        """An unrelated long flag must not end the scan before the operand."""
        self.assertEqual(warning_for("rm -rf --preserve-root /"), DESTROY_ROOT)

    def test_long_flags_before_combined_short_flag(self):
        """Order-independence across long and short spellings together."""
        self.assertEqual(warning_for("rm --force --recursive /"), DESTROY_ROOT)


class TestRmWithoutBothFlagsIsNotFlagged(unittest.TestCase):
    """Neither half of the pair means the command is not a filesystem wipe."""

    def test_force_only(self):
        """`rm -f /` cannot recurse, so it must not claim a filesystem wipe."""
        self.assertEqual(warning_for("rm -f /"), "")

    def test_recursive_only(self):
        """`rm -r /` prompts interactively instead of wiping silently."""
        self.assertEqual(warning_for("rm -r /"), "")

    def test_force_only_long_flag(self):
        """`--force` alone sets only the force half."""
        self.assertEqual(warning_for("rm --force /"), "")

    def test_recursive_only_long_flag(self):
        """`--recursive` alone sets only the recursive half."""
        self.assertEqual(warning_for("rm --recursive /"), "")


class TestRmSubdirectoryTargetsAreNotFlagged(unittest.TestCase):
    """The token split that avoids substring false positives must survive."""

    def test_subdirectory_path(self):
        """`rm -rf /tmp/x` must not match `rm -rf /`."""
        self.assertEqual(warning_for("rm -rf /tmp/x"), "")

    def test_root_prefixed_path_is_not_root(self):
        """`/var/log` is a real target, not the root operand."""
        self.assertEqual(warning_for("rm -rf /var/log"), "")

    def test_root_appearing_after_another_operand(self):
        """Scanning stops at the first operand, so a later `/` is unrelated."""
        self.assertEqual(warning_for("rm -rf /tmp && ls /"), "")


class TestRmFlagScanStopsAtOperand(unittest.TestCase):
    """The operand check still terminates the scan on a non-root path."""

    def test_plain_removal_is_allowed(self):
        """Removing files by name carries no risk at all."""
        self.assertEqual(warning_for("rm notes.txt"), "")

    def test_relative_path_target(self):
        """A relative target is never the filesystem root."""
        self.assertEqual(warning_for("rm -rf build/"), "")


if __name__ == "__main__":
    unittest.main()
