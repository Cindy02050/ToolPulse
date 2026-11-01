from toolpulse import StepObservation, ToolPulse


def test_inspection_retains_events_even_when_renderer_drops_hints():
    class Drop:
        def render(self, events, ctx):
            return []
    pulse = ToolPulse.for_swe_repo(hint_renderer=Drop())
    step = StepObservation('str_replace_editor str_replace a.py')
    result = pulse.inspect_action(step)
    assert [event.type for event in result.events] == ['blind_action']
    assert result.hints == []
    assert pulse.state.total_actions_seen == 0
    assert pulse.observe_action(step) == []


def test_observe_action_remains_hint_only_and_emits_once():
    pulse = ToolPulse.for_swe_repo()
    step = StepObservation('str_replace_editor str_replace a.py')
    result = pulse.inspect_action(step)
    assert result.hints[0].event == result.events[0]
    assert pulse.hints == result.hints
    assert pulse.observe_action(step) == result.hints
    assert len(pulse.hints) == 2
