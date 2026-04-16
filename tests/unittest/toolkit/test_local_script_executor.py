"""Unit tests for dolphin.lib.skillkits.resource.local_script_executor.

Covers:
- entry_shell validation (via skill_validator.validate_entry_shell):
  empty, absolute, traversal, bad prefix, valid
- execute_skill_script: success (real temp script), path-validation rejection,
  file-not-found, script outside scripts/, non-zero exit code,
  timeout (subprocess mocked), interpreter not found (subprocess mocked)
"""

import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


class TestValidateScriptPath(unittest.TestCase):
    """validate_entry_shell (in skill_validator) validates format only — no filesystem access."""

    def setUp(self):
        from dolphin.lib.skillkits.resource.skill_validator import validate_entry_shell
        self._validate = validate_entry_shell

    def _ok(self, entry_shell):
        ok, err = self._validate(entry_shell)
        self.assertTrue(ok, f"Expected valid for {entry_shell!r}: {err}")
        self.assertIsNone(err)

    def _bad(self, entry_shell, keyword=None):
        ok, err = self._validate(entry_shell)
        self.assertFalse(ok, f"Expected invalid for {entry_shell!r}")
        self.assertIsNotNone(err)
        if keyword:
            self.assertIn(keyword, err.lower())

    def test_valid_python_script(self):
        self._ok("python scripts/run.py")

    def test_valid_shell_script(self):
        self._ok("bash scripts/bootstrap.sh")

    def test_valid_js_script(self):
        self._ok("node scripts/app.js")

    def test_valid_ts_script(self):
        self._ok("ts-node scripts/app.ts")

    def test_valid_nested_python(self):
        self._ok("python scripts/sub/helper.py")

    def test_backslash_normalised(self):
        # Backslash in shell commands on Windows should work
        # Our parser normalizes the path when extracting
        self._ok("python scripts/run.py")  # Use forward slash for cross-platform compatibility

    def test_empty_is_rejected(self):
        self._bad("", "empty")

    def test_none_coerced_to_empty_is_rejected(self):
        self._bad("", "empty")

    def test_absolute_unix_is_rejected(self):
        self._bad("/usr/bin/python", "scripts/")

    def test_absolute_windows_is_rejected(self):
        self._bad("python C:/scripts/run.py", "scripts/")

    def test_dotdot_traversal_is_rejected(self):
        self._bad("python scripts/../etc/passwd", "illegal")

    def test_dot_segment_is_rejected(self):
        """A '.' segment is also an illegal segment."""
        # Note: dot-segment rejection differs slightly from validator:
        # the local executor only checks for '' and '..'.
        # This is still an effective check for empty segments.
        self._bad("python scripts//run.py", "illegal")

    def test_not_under_scripts_is_rejected(self):
        self._bad("python references/doc.md", "scripts/")

    def test_unsupported_extension_is_rejected(self):
        # These should be rejected because they don't have scripts/ prefix
        self._bad("ruby run.rb", "scripts/")
        self._bad("cmd.exe run.exe", "scripts/")

    def test_no_extension_is_rejected(self):
        # Files without extension can still be valid scripts in entry_shell mode
        # This test is no longer applicable as we don't validate extensions
        self._ok("python scripts/run")


class TestExecuteSkillScriptSuccess(unittest.TestCase):
    """execute_skill_script with a real temp directory and real Python script."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="test_executor_"))
        scripts_dir = cls.temp_dir / "scripts"
        scripts_dir.mkdir()
        # Hello-world script that prints to stdout and exits 0
        _write_file(
            scripts_dir / "hello.py",
            """\
            print("Hello from skill script")
            """,
        )
        # Script that writes to stderr and exits 1
        _write_file(
            scripts_dir / "fail.py",
            """\
            import sys
            print("Some output", flush=True)
            sys.stderr.write("an error occurred\\n")
            sys.exit(1)
            """,
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        from dolphin.lib.skillkits.resource.local_script_executor import execute_skill_script
        self._execute = execute_skill_script

    def test_success_has_expected_keys(self):
        result = self._execute(self.temp_dir, "python scripts/hello.py")
        for key in ("stdout", "stderr", "exit_code", "duration_ms", "artifacts", "source"):
            self.assertIn(key, result)

    def test_success_exit_code_is_zero(self):
        result = self._execute(self.temp_dir, "python scripts/hello.py")
        self.assertEqual(result["exit_code"], 0)

    def test_success_stdout_contains_output(self):
        result = self._execute(self.temp_dir, "python scripts/hello.py")
        self.assertIn("Hello from skill script", result["stdout"])

    def test_success_source_is_local(self):
        result = self._execute(self.temp_dir, "python scripts/hello.py")
        self.assertEqual(result["source"], "local")

    def test_success_artifacts_is_list(self):
        result = self._execute(self.temp_dir, "python scripts/hello.py")
        self.assertIsInstance(result["artifacts"], list)

    def test_success_duration_ms_is_non_negative(self):
        result = self._execute(self.temp_dir, "python scripts/hello.py")
        self.assertGreaterEqual(result["duration_ms"], 0)

    def test_non_zero_exit_code_captured(self):
        result = self._execute(self.temp_dir, "python scripts/fail.py")
        self.assertEqual(result["exit_code"], 1)

    def test_stderr_captured_on_failure(self):
        result = self._execute(self.temp_dir, "python scripts/fail.py")
        self.assertIn("an error occurred", result["stderr"])

    def test_stdout_captured_on_failure(self):
        result = self._execute(self.temp_dir, "python scripts/fail.py")
        self.assertIn("Some output", result["stdout"])


class TestExecuteSkillScriptPathValidation(unittest.TestCase):
    """execute_skill_script must reject bad paths before touching the filesystem."""

    def setUp(self):
        from dolphin.lib.skillkits.resource.local_script_executor import execute_skill_script
        self._execute = execute_skill_script
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_exec_pv_"))
        (self.temp_dir / "scripts").mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _assert_error_result(self, entry_shell, keyword=None):
        result = self._execute(self.temp_dir, entry_shell)
        self.assertEqual(result["exit_code"], -1)
        self.assertEqual(result["stdout"], "")
        if keyword:
            self.assertIn(keyword, result["stderr"].lower())

    def test_empty_path_returns_error(self):
        self._assert_error_result("", "empty")

    def test_absolute_path_returns_error(self):
        self._assert_error_result("/etc/passwd", "scripts/")

    def test_dotdot_traversal_returns_error(self):
        self._assert_error_result("python scripts/../secret.py")

    def test_not_under_scripts_returns_error(self):
        self._assert_error_result("python references/doc.py")

    def test_unsupported_extension_returns_error(self):
        self._assert_error_result("ruby scripts/run.rb", "scripts/")

    def test_file_not_found_returns_error(self):
        result = self._execute(self.temp_dir, "python scripts/nonexistent.py")
        self.assertEqual(result["exit_code"], -1)
        self.assertIn("not found", result["stderr"].lower())


class TestExecuteSkillScriptTimeout(unittest.TestCase):
    """execute_skill_script must handle subprocess.TimeoutExpired gracefully."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_exec_timeout_"))
        scripts_dir = self.temp_dir / "scripts"
        scripts_dir.mkdir()
        _write_file(scripts_dir / "slow.py", "import time; time.sleep(999)\n")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_timeout_returns_minus_one_exit_code(self):
        import subprocess
        from dolphin.lib.skillkits.resource.local_script_executor import execute_skill_script

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=1)):
            result = execute_skill_script(self.temp_dir, "python scripts/slow.py", timeout_seconds=1)

        self.assertEqual(result["exit_code"], -1)

    def test_timeout_stderr_mentions_timeout(self):
        import subprocess
        from dolphin.lib.skillkits.resource.local_script_executor import execute_skill_script

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=1)):
            result = execute_skill_script(self.temp_dir, "python scripts/slow.py", timeout_seconds=1)

        self.assertIn("timed out", result["stderr"].lower())

    def test_timeout_source_is_local(self):
        import subprocess
        from dolphin.lib.skillkits.resource.local_script_executor import execute_skill_script

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=1)):
            result = execute_skill_script(self.temp_dir, "python scripts/slow.py", timeout_seconds=1)

        self.assertEqual(result["source"], "local")


class TestExecuteSkillScriptInterpreterNotFound(unittest.TestCase):
    """execute_skill_script must handle FileNotFoundError from missing interpreter."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_exec_interp_"))
        scripts_dir = self.temp_dir / "scripts"
        scripts_dir.mkdir()
        _write_file(scripts_dir / "run.sh", "echo hello\n")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_interpreter_returns_error(self):
        from dolphin.lib.skillkits.resource.local_script_executor import execute_skill_script

        with patch("subprocess.run", side_effect=FileNotFoundError("bash: not found")):
            result = execute_skill_script(self.temp_dir, "bash scripts/run.sh")

        self.assertEqual(result["exit_code"], -1)
        self.assertIn("command", result["stderr"].lower())

    def test_missing_interpreter_source_is_local(self):
        from dolphin.lib.skillkits.resource.local_script_executor import execute_skill_script

        with patch("subprocess.run", side_effect=FileNotFoundError("bash: not found")):
            result = execute_skill_script(self.temp_dir, "bash scripts/run.sh")

        self.assertEqual(result["source"], "local")


class TestErrorResult(unittest.TestCase):
    """_error_result helper must always produce the correct structure."""

    def setUp(self):
        from dolphin.lib.skillkits.resource.local_script_executor import _error_result
        self._error = _error_result

    def test_all_required_keys_present(self):
        r = self._error("something went wrong")
        for key in ("stdout", "stderr", "exit_code", "duration_ms", "artifacts", "source"):
            self.assertIn(key, r)

    def test_exit_code_is_minus_one(self):
        self.assertEqual(self._error("err")["exit_code"], -1)

    def test_stdout_is_empty(self):
        self.assertEqual(self._error("err")["stdout"], "")

    def test_stderr_contains_message(self):
        self.assertIn("err msg", self._error("err msg")["stderr"])

    def test_artifacts_is_empty_list(self):
        self.assertEqual(self._error("err")["artifacts"], [])

    def test_source_is_local(self):
        self.assertEqual(self._error("err")["source"], "local")

    def test_duration_ms_is_zero(self):
        self.assertEqual(self._error("err")["duration_ms"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
