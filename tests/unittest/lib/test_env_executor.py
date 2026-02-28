"""Tests for LocalExecutor.exec_python error handling."""

import os
import tempfile

from dolphin.lib.vm.env_executor import LocalExecutor


def _make_executor() -> LocalExecutor:
    return LocalExecutor(working_dir=tempfile.gettempdir())


class TestExecPythonErrorHints:
    """exec_python should return actionable hints for common errors."""

    def test_name_error_includes_hint(self):
        executor = _make_executor()
        result = executor.exec_python("extract_ai_summary(data)")
        assert "NameError" in result
        assert "[Hint]" in result
        assert "define the function" in result

    def test_module_not_found_includes_hint(self):
        executor = _make_executor()
        result = executor.exec_python("import nonexistent_module_xyz")
        assert "ModuleNotFoundError" in result
        assert "[Hint]" in result
        assert "not installed" in result

    def test_successful_execution_no_hint(self):
        executor = _make_executor()
        result = executor.exec_python("print('hello')")
        assert "[Hint]" not in result
        assert "hello" in result

    def test_other_errors_no_hint(self):
        executor = _make_executor()
        result = executor.exec_python("1 / 0")
        assert "ZeroDivisionError" in result
        assert "[Hint]" not in result
