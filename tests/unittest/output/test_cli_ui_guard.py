import importlib.abc
import importlib.util
import sys

from dolphin.core.logging.logger import (
    console_block_start,
    console_skill_call,
    console_skill_response,
)


class _BlockCliConsoleImportFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "dolphin.cli.ui.console":
            raise AssertionError("CLI UI should not be imported when stdout is not a TTY.")
        return None


def test_console_helpers_do_not_import_cli_ui_when_not_tty(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)

    finder = _BlockCliConsoleImportFinder()
    sys.meta_path.insert(0, finder)
    try:
        console_skill_call("test_skill", {"param": "value"}, verbose=True)
        console_skill_response("test_skill", {"ok": True}, verbose=True)
        console_block_start("explore", "out", "content", verbose=True)
    finally:
        sys.meta_path.remove(finder)
