from dolphin.cli.ui.state import _pause_active_components, set_active_plan_card, set_active_status_bar


class _DummyStatusBar:
    def __init__(self, *, running=True, paused=False, fixed_row=None):
        self.running = running
        self.paused = paused
        self.fixed_row = fixed_row
        self.pause_calls = 0

    def pause(self):
        self.pause_calls += 1
        self.paused = True


class _DummyPlanCard:
    def __init__(self, *, running=True, paused=False, fixed_row_start=None):
        self.running = running
        self.paused = paused
        self.fixed_row_start = fixed_row_start
        self.pause_calls = 0

    def pause(self):
        self.pause_calls += 1
        self.paused = True


def test_pause_active_components_skips_fixed_row_components():
    status_bar = _DummyStatusBar(fixed_row=10)
    plan_card = _DummyPlanCard(fixed_row_start=5)
    set_active_status_bar(status_bar)
    set_active_plan_card(plan_card)

    paused = _pause_active_components()
    assert paused == []
    assert status_bar.pause_calls == 0
    assert plan_card.pause_calls == 0


def test_pause_active_components_pauses_inline_components():
    status_bar = _DummyStatusBar(fixed_row=None)
    plan_card = _DummyPlanCard(fixed_row_start=None)
    set_active_status_bar(status_bar)
    set_active_plan_card(plan_card)

    paused = _pause_active_components()
    assert len(paused) == 2
    assert status_bar.pause_calls == 1
    assert plan_card.pause_calls == 1

