import json

import toolpulse
from toolpulse import BlindActionEvent, Hint, TemplateHintRenderer, ToolPulse


def _hints():
    event = BlindActionEvent('edit', 'a.py', 'edit a.py')
    return [Hint(event, 'first hint'), Hint(event, 'second hint')]


def test_default_appends_matching_tags_and_one_hint_per_line():
    assert toolpulse.assemble_observation('tool output', _hints()) == (
        'tool output\n<tool_pulse>\nfirst hint\nsecond hint\n</tool_pulse>'
    )


def test_different_message_type_returns_serialized_json():
    text = toolpulse.assemble_observation('原始输出\n"quoted"', _hints(), hint_set_name='different_message_type')
    assert isinstance(text, str)
    assert json.loads(text) == {'observation': '原始输出\n"quoted"', 'hint': 'first hint\nsecond hint'}
    assert '原始输出' in text


def test_no_hints_preserves_plain_observation():
    assert toolpulse.assemble_observation('original\n', []) == 'original\n'


def test_no_hints_json_keeps_stable_schema():
    assert json.loads(toolpulse.assemble_observation('original', [], hint_set_name='different_message_type')) == {
        'observation': 'original', 'hint': '',
    }


def test_empty_observation_and_multiline_hint_text_are_preserved():
    hint = Hint(BlindActionEvent('edit', 'a.py', 'edit a.py'), 'notice\nguidance')
    assert toolpulse.assemble_observation('', [hint]) == '<tool_pulse>\nnotice\nguidance\n</tool_pulse>'


def test_other_hint_sets_use_tagged_format_without_mutating_hints():
    hints = _hints()
    original = list(hints)
    assert toolpulse.assemble_observation('out', hints, hint_set_name='llm_coach') == toolpulse.assemble_observation('out', hints)
    assert hints == original


def test_middleware_assembly_uses_renderer_hint_set_and_allows_override():
    pulse = ToolPulse.for_swe_repo(hint_renderer=TemplateHintRenderer(hint_set_name='different_message_type'))
    hints = _hints()
    assert json.loads(pulse.assemble_observation('out', hints))['hint'] == 'first hint\nsecond hint'
    assert pulse.assemble_observation('out', hints, hint_set_name='remind_only') == toolpulse.assemble_observation('out', hints)
    assert pulse.state.total_actions_seen == 0
    assert pulse.hints == []


def test_real_observe_to_assembled_context():
    from toolpulse import StepObservation
    pulse = ToolPulse.for_swe_repo()
    step = StepObservation('open a.py', observation='file contents')
    pulse.observe_step(step)
    pulse.observe_step(step)
    hints = pulse.observe_step(step)
    text = pulse.assemble_observation(step.observation, hints)
    assert text == f'file contents\n<tool_pulse>\n{hints[0].text}\n</tool_pulse>'
