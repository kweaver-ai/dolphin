from dolphin.cli.ui.state import set_active_status_bar
from dolphin.cli.ui.stream_renderer import _is_fixed_layout_active


class _DummyStatusBar:
    def __init__(self, fixed_row):
        self.fixed_row = fixed_row


def test_is_fixed_layout_active_false_when_no_status_bar():
    set_active_status_bar(None)
    assert _is_fixed_layout_active() is False


def test_is_fixed_layout_active_true_when_fixed_row_set():
    set_active_status_bar(_DummyStatusBar(fixed_row=10))
    assert _is_fixed_layout_active() is True


def test_is_fixed_layout_active_false_when_fixed_row_none():
    set_active_status_bar(_DummyStatusBar(fixed_row=None))
    assert _is_fixed_layout_active() is False

