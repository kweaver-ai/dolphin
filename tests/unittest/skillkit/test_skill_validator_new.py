"""Unit tests for the new path-validation helpers in skill_validator.py.

Covers the functions added to support the unified skill contract:
- _reject_bad_path_segments
- _matches_allowed_prefix
- validate_skill_file_path
- validate_skill_script_path
- validate_entry_shell
- get_script_path_from_entry_shell
"""

import unittest

from dolphin.lib.skillkits.resource.skill_validator import (
    _reject_bad_path_segments,
    _matches_allowed_prefix,
    validate_skill_file_path,
    validate_skill_script_path,
    validate_entry_shell,
    get_script_path_from_entry_shell,
)


class TestRejectBadPathSegments(unittest.TestCase):
    """_reject_bad_path_segments should catch '.', '..', and empty segments."""

    def test_normal_path_returns_none(self):
        self.assertIsNone(_reject_bad_path_segments("references/guide.md", "references/guide.md"))

    def test_single_filename_returns_none(self):
        self.assertIsNone(_reject_bad_path_segments("SKILL.md", "SKILL.md"))

    def test_nested_path_returns_none(self):
        self.assertIsNone(_reject_bad_path_segments("scripts/sub/run.py", "scripts/sub/run.py"))

    def test_dotdot_segment_returns_error(self):
        result = _reject_bad_path_segments("references/../etc/passwd", "references/../etc/passwd")
        self.assertIsNotNone(result)
        self.assertIn("..", result)

    def test_dot_segment_returns_error(self):
        result = _reject_bad_path_segments("references/./a.md", "references/./a.md")
        self.assertIsNotNone(result)
        self.assertIn(".", result)

    def test_double_slash_produces_empty_segment(self):
        result = _reject_bad_path_segments("a//b", "a//b")
        self.assertIsNotNone(result)

    def test_original_path_appears_in_error(self):
        original = "references/../secret"
        result = _reject_bad_path_segments("references/../secret", original)
        self.assertIn(original, result)

    def test_dotdot_at_start(self):
        result = _reject_bad_path_segments("../etc/passwd", "../etc/passwd")
        self.assertIsNotNone(result)

    def test_dotdot_at_end(self):
        result = _reject_bad_path_segments("references/..", "references/..")
        self.assertIsNotNone(result)

    def test_only_dot(self):
        result = _reject_bad_path_segments(".", ".")
        self.assertIsNotNone(result)

    def test_only_dotdot(self):
        result = _reject_bad_path_segments("..", "..")
        self.assertIsNotNone(result)


class TestMatchesAllowedPrefix(unittest.TestCase):
    """_matches_allowed_prefix enforces exact match for tokens and prefix match for dirs."""

    PREFIXES = ("SKILL.md", "references/", "scripts/")

    def _check(self, path, expected):
        result = _matches_allowed_prefix(path, self.PREFIXES)
        self.assertEqual(result, expected, f"Unexpected result for path: {path!r}")

    def test_skill_md_exact_is_allowed(self):
        self._check("SKILL.md", True)

    def test_skill_md_with_extra_suffix_is_rejected(self):
        self._check("SKILL.md.extra.md", False)

    def test_skill_md_with_leading_slash_is_rejected(self):
        self._check("/SKILL.md", False)

    def test_references_file_is_allowed(self):
        self._check("references/guide.md", True)

    def test_references_bare_is_rejected(self):
        """'references/' with nothing after it must not be allowed."""
        self._check("references/", False)

    def test_references_nested_is_allowed(self):
        self._check("references/subdir/doc.txt", True)

    def test_scripts_file_is_allowed(self):
        self._check("scripts/run.py", True)

    def test_scripts_bare_is_rejected(self):
        self._check("scripts/", False)

    def test_unrelated_path_is_rejected(self):
        self._check("README.md", False)

    def test_empty_string_is_rejected(self):
        self._check("", False)

    def test_scripts_only_prefix_tuple(self):
        result = _matches_allowed_prefix("scripts/foo.py", ("scripts/",))
        self.assertTrue(result)
        result = _matches_allowed_prefix("references/foo.md", ("scripts/",))
        self.assertFalse(result)


class TestValidateSkillFilePath(unittest.TestCase):
    """validate_skill_file_path must accept design-compliant paths and reject everything else."""

    def _ok(self, path):
        ok, err = validate_skill_file_path(path)
        self.assertTrue(ok, f"Expected valid but got error for {path!r}: {err}")
        self.assertIsNone(err)

    def _bad(self, path, keyword=None):
        ok, err = validate_skill_file_path(path)
        self.assertFalse(ok, f"Expected invalid but got valid for {path!r}")
        self.assertIsNotNone(err)
        if keyword:
            self.assertIn(keyword, err.lower())

    # ---- Valid paths --------------------------------------------------------

    def test_skill_md_exact(self):
        self._ok("SKILL.md")

    def test_references_file(self):
        self._ok("references/guide.md")

    def test_references_json_file(self):
        self._ok("references/data.json")

    def test_scripts_python_file(self):
        self._ok("scripts/run.py")

    def test_scripts_shell_file(self):
        self._ok("scripts/bootstrap.sh")

    def test_scripts_nested(self):
        self._ok("scripts/sub/helper.py")

    def test_backslashes_converted(self):
        """Windows-style backslashes should be normalised to forward slashes."""
        ok, err = validate_skill_file_path("references\\guide.md")
        self.assertTrue(ok, f"Backslash path should be normalised: {err}")

    # ---- Invalid paths ------------------------------------------------------

    def test_empty_string_is_rejected(self):
        self._bad("", "empty")

    def test_whitespace_only_is_rejected(self):
        self._bad("   ", "empty")

    def test_absolute_unix_path_is_rejected(self):
        self._bad("/etc/passwd", "absolute")

    def test_absolute_windows_path_is_rejected(self):
        self._bad("C:/secret", "absolute")

    def test_dotdot_traversal_is_rejected(self):
        self._bad("references/../etc/passwd")

    def test_dot_segment_is_rejected(self):
        self._bad("references/./a.md")

    def test_skill_md_with_extra_suffix_is_rejected(self):
        self._bad("SKILL.md.extra.md")

    def test_references_bare_is_rejected(self):
        self._bad("references/")

    def test_scripts_bare_is_rejected(self):
        self._bad("scripts/")

    def test_readme_md_is_rejected(self):
        self._bad("README.md")

    def test_double_slash_is_rejected(self):
        self._bad("references//guide.md")

    def test_dotdot_at_start_is_rejected(self):
        self._bad("../etc/passwd")


class TestValidateSkillScriptPath(unittest.TestCase):
    """validate_skill_script_path must only allow scripts/<something> paths."""

    def _ok(self, path):
        ok, err = validate_skill_script_path(path)
        self.assertTrue(ok, f"Expected valid but got error for {path!r}: {err}")
        self.assertIsNone(err)

    def _bad(self, path, keyword=None):
        ok, err = validate_skill_script_path(path)
        self.assertFalse(ok, f"Expected invalid but got valid for {path!r}")
        self.assertIsNotNone(err)
        if keyword:
            self.assertIn(keyword, err.lower())

    # ---- Valid paths --------------------------------------------------------

    def test_scripts_python(self):
        self._ok("scripts/analyze.py")

    def test_scripts_shell(self):
        self._ok("scripts/run.sh")

    def test_scripts_js(self):
        self._ok("scripts/index.js")

    def test_scripts_nested(self):
        self._ok("scripts/sub/helper.py")

    def test_backslashes_normalised(self):
        ok, err = validate_skill_script_path("scripts\\analyze.py")
        self.assertTrue(ok, f"Backslash path should be normalised: {err}")

    # ---- Invalid paths ------------------------------------------------------

    def test_empty_is_rejected(self):
        self._bad("", "empty")

    def test_whitespace_only_is_rejected(self):
        self._bad("   ", "empty")

    def test_absolute_unix_is_rejected(self):
        self._bad("/usr/bin/python", "absolute")

    def test_absolute_windows_is_rejected(self):
        self._bad("C:/scripts/run.py", "absolute")

    def test_dotdot_traversal_is_rejected(self):
        self._bad("scripts/../etc/passwd")

    def test_dot_segment_is_rejected(self):
        self._bad("scripts/./run.py")

    def test_references_path_is_rejected(self):
        self._bad("references/doc.md")

    def test_skill_md_is_rejected(self):
        self._bad("SKILL.md")

    def test_scripts_bare_is_rejected(self):
        self._bad("scripts/")

    def test_double_slash_is_rejected(self):
        self._bad("scripts//run.py")

    def test_dotdot_at_start_is_rejected(self):
        self._bad("../scripts/run.py")


class TestValidateEntryShell(unittest.TestCase):
    """validate_entry_shell must accept safe commands and reject injection patterns."""

    def _ok(self, cmd):
        ok, err = validate_entry_shell(cmd)
        self.assertTrue(ok, f"Expected valid but got error for {cmd!r}: {err}")
        self.assertIsNone(err)

    def _bad(self, cmd, keyword=None):
        ok, err = validate_entry_shell(cmd)
        self.assertFalse(ok, f"Expected invalid but got valid for {cmd!r}")
        self.assertIsNotNone(err)
        if keyword:
            self.assertIn(keyword, err.lower())

    # ---- Valid commands --------------------------------------------------------

    def test_python_script(self):
        self._ok("python scripts/analyze.py")

    def test_python3_script(self):
        self._ok("python3 scripts/run.py")

    def test_bash_script(self):
        self._ok("bash scripts/run.sh")

    def test_node_script(self):
        self._ok("node scripts/process.js")

    def test_script_with_args(self):
        self._ok("python scripts/analyze.py --input data.csv")

    def test_script_nested_path(self):
        self._ok("python scripts/sub/helper.py")

    def test_backslash_normalised(self):
        self._ok("python scripts\\analyze.py")

    # ---- Forbidden: -c flag (shell injection) ----------------------------------

    def test_python_c_is_rejected(self):
        self._bad("python -c 'import os; os.system(\"rm -rf /\")'", "-c")

    def test_bash_c_is_rejected(self):
        self._bad("bash -c 'cat /etc/passwd'", "-c")

    def test_sh_c_is_rejected(self):
        self._bad("sh -c 'id'", "-c")

    def test_python_c_before_scripts_is_rejected(self):
        """Even if scripts/ appears later, -c at position 1 must be blocked."""
        self._bad("python -c 'print(1)' scripts/x.py", "-c")

    # ---- Forbidden: -m flag (module execution) ---------------------------------

    def test_python_m_is_rejected(self):
        self._bad("python -m http.server", "-m")

    def test_python_m_before_scripts_is_rejected(self):
        self._bad("python -m scripts.analyze", "-m")

    # ---- Missing or wrong script path structure --------------------------------

    def test_empty_is_rejected(self):
        self._bad("", "empty")

    def test_single_token_is_rejected(self):
        self._bad("python")

    def test_bare_script_path_is_rejected(self):
        """A bare 'scripts/x.py' without interpreter must be rejected."""
        self._bad("scripts/analyze.py")

    def test_references_path_is_rejected(self):
        self._bad("python references/guide.md")

    def test_absolute_script_path_is_rejected(self):
        self._bad("python /usr/local/scripts/run.py")

    def test_dotdot_traversal_in_script_is_rejected(self):
        self._bad("python scripts/../etc/passwd")


class TestGetScriptPathFromEntryShell(unittest.TestCase):
    """get_script_path_from_entry_shell must extract tokens[1] after validation."""

    def test_extracts_python_script(self):
        assert get_script_path_from_entry_shell("python scripts/analyze.py") == "scripts/analyze.py"

    def test_extracts_with_args(self):
        assert get_script_path_from_entry_shell("python scripts/run.py --flag") == "scripts/run.py"

    def test_normalises_backslash(self):
        assert get_script_path_from_entry_shell("python scripts\\run.py") == "scripts/run.py"

    def test_nested_path(self):
        assert get_script_path_from_entry_shell("bash scripts/sub/run.sh") == "scripts/sub/run.sh"


if __name__ == "__main__":
    unittest.main(verbosity=2)
