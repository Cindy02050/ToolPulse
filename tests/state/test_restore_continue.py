# tests/state/test_restore_continue.py
"""Restore→continue equivalence: snapshotting mid-stream must be invisible.

Drives the same 18-step eventful stream through (i) one continuous run and
(ii) a run that ``snapshot()``s at step 9 into a NEW ``SessionState`` and
continues; asserts the two runs' per-step event streams and final state are
identical.

Pattern disclosure: this test drives detector + state DIRECTLY (mirroring
tests/detectors/test_multi_granularity.py's ``_analyze`` append-then-analyze
convention) instead of re-wiring ``ToolPulse`` — ``pulse.state`` is a read-only
property backed by ``_state``, so clean middleware re-wiring would require
``pulse2.__dict__["_state"]`` assignment.  The middleware-free pattern tests
the same contract without touching private plumbing: a fresh detector instance
(detectors hold no mutable detection state, D6) over the restored state.
"""
from toolpulse.core.types import ActionRecord, StepObservation
from toolpulse.detectors.multi_granularity import MultiGranularityDetector
from toolpulse.parsing.sweagent import SweAgentParser
from toolpulse.semantics.repo.labeler import RepoLabeler
from toolpulse.state.session import SessionState

CONFIG = dict(window_sizes=(3,), repeat_times_for_loop=3, repeat_times_for_stalled=3,
              min_actions_before_stalled=3, stalled_cooldown_steps=12,
              max_history=50, offline=True)

TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "tests/test_a.py", line 3, in test_add\n'
    "    assert add(1, 1) == 3\n"
    "E   AssertionError: assert 1 == 2\n"
    "=========================== 1 failed in 0.05s ============================"
)


def _steps() -> list[StepObservation]:
    steps = []
    for _ in range(6):   # 6 cycles x 3 = 18 eventful steps (failed/loop/stalled)
        steps.append(StepObservation(raw_action="open src/a.py",
                                     observation="1: def add(a, b):\n2:     return a - b",
                                     thought="look", execution_time=0.4))
        steps.append(StepObservation(raw_action="timeout 30 python -m pytest tests/test_a.py",
                                     observation=TRACEBACK, thought="run", execution_time=2.1))
        steps.append(StepObservation(raw_action="timeout 30 python -m pytest tests/test_a.py",
                                     observation=TRACEBACK, thought="run again", execution_time=2.0))
    return steps


def _drive(state: SessionState, detector: MultiGranularityDetector,
           steps: list[StepObservation]) -> list[list[dict]]:
    """Append-then-analyze, the middleware's canonical D15 order."""
    parser, labeler = SweAgentParser(), RepoLabeler("python")
    per_step = []
    for step in steps:
        action = parser.parse(step)
        info = labeler.label(action, step, state, record=True)
        record = ActionRecord(action=action, label=info,
                              step_index=state.total_actions_seen,
                              thought=step.thought, observation=step.observation,
                              execution_time=step.execution_time)
        state.append(record)
        per_step.append([e.to_dict() for e in detector.analyze(step, record, state)])
    return per_step


def test_restore_at_step_9_continues_identically():
    steps = _steps()

    # (i) one continuous run
    continuous_state = SessionState(stalled_cooldown_steps=12)
    continuous_events = _drive(continuous_state, MultiGranularityDetector(**CONFIG), steps)

    # (ii) snapshot at step 9 into a NEW SessionState, then continue
    first_state = SessionState(stalled_cooldown_steps=12)
    head_events = _drive(first_state, MultiGranularityDetector(**CONFIG), steps[:9])
    resumed_state = SessionState(stalled_cooldown_steps=12)
    resumed_state.restore(first_state.snapshot())
    tail_events = _drive(resumed_state, MultiGranularityDetector(**CONFIG), steps[9:])

    assert head_events + tail_events == continuous_events   # per-step streams identical
    assert any(e["type"] == "failed_action" for s in tail_events for e in s)   # eventful tail

    # final state equivalence
    assert resumed_state.total_actions_seen == continuous_state.total_actions_seen == 18
    assert [r.action for r in resumed_state.actions] == [r.action for r in continuous_state.actions]
    assert resumed_state.grammar.symbols == continuous_state.grammar.symbols
    assert resumed_state.failures.snapshot() == continuous_state.failures.snapshot()
    assert resumed_state.last_stalled_step == continuous_state.last_stalled_step
    assert resumed_state.features.rows == continuous_state.features.rows
    assert resumed_state.score_history == continuous_state.score_history
    assert resumed_state.reported_stalled_patterns == continuous_state.reported_stalled_patterns
    assert resumed_state.repeated_production_reported == continuous_state.repeated_production_reported
    assert resumed_state.files.snapshot() == continuous_state.files.snapshot()
