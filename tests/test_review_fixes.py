"""Regressions for the explicitly selected independent-review findings."""
import copy
import json
from pathlib import Path

import pytest

from toolpulse import (
    Action, BlindActionEvent, CallbackSink, FailedActionEvent, Hint, HintContext,
    LLMHintProvider, ListSink, MultiGranularityDetector, StepObservation, ToolPulse,
)
from toolpulse.semantics.repo.errors import observation_error_fingerprint


@pytest.mark.parametrize('language,command,observation', [
    ('cpp', 'g++ main.cpp', 'main.cpp:1:1: error: missing semicolon'),
    ('cpp', './reproduce', 'Segmentation fault (core dumped)'),
    ('java', 'javac Main.java', 'Main.java:1: error: cannot find symbol'),
    ('java', 'java Main', 'Exception in thread "main" java.lang.NullPointerException'),
    ('python', 'python run.py', 'error: operation failed'),
])
def test_recognized_errors_reach_failure_hints(language, command, observation):
    pulse = ToolPulse.for_swe_repo(language)
    pulse.observe_step(StepObservation(command, observation=observation))
    hints = pulse.observe_step(StepObservation(command, observation=observation))
    assert any(h.event.type == 'failed_action' for h in hints)


def test_fingerprint_fallback_handles_unknown_diagnostics_and_preserves_specifics():
    assert observation_error_fingerprint('opaque diagnostic', 'runtime') == 'opaque diagnostic'
    assert observation_error_fingerprint('heading\n\x1b[31m fatal: bad symbol \x1b[0m\nfooter', 'syntax') == 'fatal: bad symbol'
    assert observation_error_fingerprint('ValueError: bad\nfooter', 'runtime') == 'ValueError: bad'
    assert observation_error_fingerprint('ok', 'none') is None
    assert observation_error_fingerprint('', 'runtime') is None


@pytest.mark.parametrize('value', ['invalid', float('nan'), float('inf'), -1.0])
def test_invalid_execution_time_does_not_mutate_session(value):
    pulse = ToolPulse.for_swe_repo()
    pulse.observe_step(StepObservation('open existing.py'))
    before = pulse.state.snapshot()
    with pytest.raises((ValueError, TypeError)):
        pulse.observe_step(StepObservation('open bad.py', execution_time=value))
    assert pulse.state.snapshot() == before
    pulse.observe_step(StepObservation('open next.py'))
    assert len(pulse.state.actions) == len(pulse.state.features) == len(pulse.state.grammar.symbols) == 2


def test_serialization_failure_rolls_back_file_grammar_and_actions():
    class Parser:
        def parse(self, step):
            args = {'mixed': {1: 'a', '2': 'b'}} if step.raw_action == 'bad' else {}
            return Action('x', args, step.raw_action)

    pulse = ToolPulse(Parser())
    pulse.observe_step(StepObservation('good'))
    before = pulse.state.snapshot()
    matrix = [row.copy() for row in pulse.state.features.matrix]
    with pytest.raises(TypeError):
        pulse.observe_step(StepObservation('bad'))
    assert pulse.state.snapshot() == before
    assert all((a == b).all() for a, b in zip(matrix, pulse.state.features.matrix))
    pulse.observe_step(StepObservation('good'))
    assert len(pulse.state.actions) == len(pulse.state.features) == len(pulse.state.grammar.symbols) == 2


def test_labeler_failure_rolls_back_its_file_changes():
    class Labeler:
        def label(self, action, step, state, *, record):
            state.files.record_edit('bad.py')
            raise RuntimeError('label failed')

    pulse = ToolPulse.for_swe_repo()
    before = pulse.state.snapshot()
    pulse.labeler = Labeler()
    with pytest.raises(RuntimeError):
        pulse.observe_step(StepObservation('edit bad.py'))
    assert pulse.state.snapshot() == before


@pytest.mark.parametrize('corruption', ['missing', 'late'])
def test_failed_restore_keeps_live_state(corruption):
    pulse = ToolPulse.for_swe_repo()
    pulse.observe_step(StepObservation('open a.py'))
    pulse.state.score_history[3] = [0.25]
    before = pulse.state.snapshot()
    data = {} if corruption == 'missing' else copy.deepcopy(before)
    if corruption == 'late':
        data['score_history'] = {'not-an-int': []}
    with pytest.raises((KeyError, ValueError, TypeError)):
        pulse.state.restore(data)
    assert pulse.state.snapshot() == before


def test_snapshot_and_restored_args_are_independent():
    pulse = ToolPulse.for_swe_repo()
    pulse.observe_step(StepObservation('open a.py'))
    snap = pulse.state.snapshot()
    snap['actions'][0]['action']['args']['path'] = 'snapshot.py'
    assert pulse.state.actions[0].action.args['path'] == 'a.py'
    pulse.state.restore(snap)
    pulse.state.actions[0].action.args['path'] = 'live.py'
    assert snap['actions'][0]['action']['args']['path'] == 'snapshot.py'


def test_parser_owned_nested_args_do_not_change_history():
    args = {'nested': {'path': 'a.py'}}
    class Parser:
        def parse(self, step):
            return Action('read', args, step.raw_action)
    pulse = ToolPulse(Parser())
    pulse.observe_step(StepObservation('read'))
    args['nested']['path'] = 'b.py'
    assert pulse.state.actions[0].action.args['nested']['path'] == 'a.py'


@pytest.mark.parametrize('kwargs', [
    {'window_sizes': (3.5,)}, {'max_history': 24.5},
    {'stalled_distance_threshold': float('nan')},
    {'repeat_times_for_loop': 2.5}, {'failed_action_window_steps': True},
])
def test_invalid_configuration_rejected_at_construction(kwargs):
    with pytest.raises(ValueError):
        MultiGranularityDetector(**kwargs)


def test_long_run_bounds_diagnostics_and_default_hints_and_reset_clears_task():
    pulse = ToolPulse.for_swe_repo(detector=MultiGranularityDetector(window_sizes=(3,), max_history=12))
    pulse.set_task_description('previous task')
    for _ in range(120):
        pulse.observe_step(StepObservation('open a.py'))
    assert len(pulse.state.actions) == len(pulse.state.features) == len(pulse.state.grammar.symbols) == 12
    assert len(pulse.state.score_history[3]) <= 12
    assert len(pulse.hints) <= 12
    pulse.reset()
    assert pulse.hints == []
    assert pulse.task_description == ''
    assert pulse.state.total_actions_seen == 0


def test_list_sink_retention_opt_out_and_batch_overflow():
    hints = [Hint(BlindActionEvent('edit', str(i), 'edit'), str(i)) for i in range(5)]
    sink = ListSink(max_hints=2)
    sink.emit(hints, None)
    assert sink.hints == hints[-2:]
    unbounded = ListSink(max_hints=None)
    unbounded.emit(hints, None)
    assert unbounded.hints == hints


@pytest.mark.parametrize('response', [None, 7, {}, b'bytes', '   '])
def test_invalid_llm_response_is_dropped(response):
    class Client:
        def complete(self, *args, **kwargs):
            return response
    provider = LLMHintProvider({'events': {'failed_action': {'prompt': 'p'}}}, Client())
    assert provider.provide([FailedActionEvent('runtime', 'x', 'fp', 2)], HintContext('task', 'obs')) == []


def test_llm_can_continue_after_invalid_response():
    class Client:
        def __init__(self):
            self.values = iter([None, ' recovered '])
        def complete(self, *args, **kwargs):
            return next(self.values)
    provider = LLMHintProvider({'events': {'failed_action': {'prompt': 'p'}}}, Client())
    events = [FailedActionEvent('runtime', 'x', 'fp', 2)] * 2
    assert [h.text for h in provider.provide(events, HintContext('t', 'o'))] == ['recovered']


def test_implementation_guide_uses_actual_optional_client_module():
    readme = (Path(__file__).parents[1] / 'docs/implementation-guide.md').read_text()
    assert 'from toolpulse.llm import OpenAIChatClient' not in readme
    assert 'from toolpulse.llm.openai_client import OpenAIChatClient' in readme


def test_packaging_uses_distribution_name():
    project = (Path(__file__).parents[1] / 'pyproject.toml').read_text()
    assert '"scikit-sequitur"' in project
    assert '"sksequitur"' not in project


def test_late_detector_failure_restores_state_and_future_events():
    control = ToolPulse.for_swe_repo(detector=MultiGranularityDetector(window_sizes=(3,), max_history=12))
    pulse = ToolPulse.for_swe_repo(detector=MultiGranularityDetector(window_sizes=(3,), max_history=12))
    prefix = ['open a.py', 'python run.py', 'rg x .'] * 5
    for command in prefix:
        step = StepObservation(command, observation='ok', execution_time=0.1)
        control.observe_step(step)
        pulse.observe_step(step)
    before = pulse.state.snapshot()
    original = pulse.detector.analyze
    def fail_after_analyzing(step, record, state):
        original(step, record, state)
        raise RuntimeError('after trim and scoring')
    pulse.detector.analyze = fail_after_analyzing
    with pytest.raises(RuntimeError):
        pulse.observe_step(StepObservation('open failed.py'))
    pulse.detector.analyze = original
    assert pulse.state.snapshot() == before
    for command in prefix:
        step = StepObservation(command, observation='ok', execution_time=0.1)
        assert pulse.observe_step(step) == control.observe_step(step)
    assert pulse.state.snapshot() == control.state.snapshot()


def test_keyboard_interrupt_rolls_back_detection():
    class Labeler:
        def label(self, action, step, state, *, record):
            state.files.record_edit('a.py')
            raise KeyboardInterrupt()
    pulse = ToolPulse(ActionParserStub(), labeler=Labeler())
    before = pulse.state.snapshot()
    with pytest.raises(KeyboardInterrupt):
        pulse.observe_step(StepObservation('x'))
    assert pulse.state.snapshot() == before


class ActionParserStub:
    def parse(self, step):
        return Action('x', {}, step.raw_action)


def test_sink_failure_keeps_completed_detection_committed():
    def fail(hints, step):
        raise RuntimeError('delivery failed')
    pulse = ToolPulse.for_swe_repo(hint_sink=CallbackSink(fail))
    step = StepObservation('open a.py')
    pulse.observe_step(step)
    pulse.observe_step(step)
    with pytest.raises(RuntimeError):
        pulse.observe_step(step)
    assert pulse.state.total_actions_seen == 3
    assert len(pulse.state.actions) == len(pulse.state.features) == len(pulse.state.grammar.symbols) == 3


def test_reset_does_not_clear_external_callback_storage():
    external = []
    pulse = ToolPulse.for_swe_repo(hint_sink=CallbackSink(lambda hints, step: external.extend(hints)))
    for _ in range(3):
        pulse.observe_step(StepObservation('open a.py'))
    pulse.reset()
    assert len(external) == 1


def test_online_json_resume_after_history_and_hint_caps():
    config = dict(window_sizes=(3,), max_history=12, stalled_cooldown_steps=4)
    def new():
        return ToolPulse.for_swe_repo(detector=MultiGranularityDetector(**config))
    continuous, head, resumed = new(), new(), new()
    steps = [StepObservation(command, observation='ok') for command in ['open a.py', 'python x.py', 'rg x .'] * 30]
    expected = [continuous.observe_step(s) for s in steps]
    actual = [head.observe_step(s) for s in steps[:41]]
    resumed.state.restore(json.loads(json.dumps(head.state.snapshot())))
    actual.extend(resumed.observe_step(s) for s in steps[41:])
    assert actual == expected
    assert resumed.state.snapshot() == continuous.state.snapshot()


@pytest.mark.parametrize('field,value', [
    ('total_actions_seen', 'bad'), ('grammar_symbols', [None]),
    ('total_actions_seen', -1), ('raw_rows', [{}]),
])
def test_invalid_snapshot_data_rejected_before_commit(field, value):
    pulse = ToolPulse.for_swe_repo()
    pulse.observe_step(StepObservation('open a.py'))
    before = pulse.state.snapshot()
    damaged = copy.deepcopy(before)
    damaged[field] = value
    with pytest.raises((ValueError, TypeError, KeyError)):
        pulse.state.restore(damaged)
    assert pulse.state.snapshot() == before


def test_generic_fingerprint_uses_diagnostic_before_compiler_count_summary():
    first = 'Main.java:1: error: cannot find symbol\n symbol: class Foo\n1 error'
    second = 'Main.java:9: error: incompatible types: String cannot be converted to int\n1 error'
    assert observation_error_fingerprint(first, 'syntax') != observation_error_fingerprint(second, 'syntax')


def test_generic_fingerprint_prefers_linker_diagnostic_over_exit_status():
    first = "/usr/bin/ld: main.cpp:(.text+0x5): undefined reference to `foo()'\ncollect2: error: ld returned 1 exit status"
    second = "/usr/bin/ld: main.cpp:(.text+0x5): undefined reference to `bar()'\ncollect2: error: ld returned 1 exit status"
    assert observation_error_fingerprint(first, 'syntax') != observation_error_fingerprint(second, 'syntax')
