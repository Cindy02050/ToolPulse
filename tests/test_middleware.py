import subprocess
import sys
from pathlib import Path

from toolpulse.core.types import LabelKind, StepObservation
from toolpulse.hints.sinks import ListSink
from toolpulse.middleware import ToolPulse
from toolpulse.parsing.sweagent import SweAgentParser
from toolpulse.semantics.repo.labeler import RepoLabeler


def _pulse():
    sink = ListSink()
    pulse = ToolPulse(parser=SweAgentParser(), labeler=RepoLabeler("python"), hint_sink=sink)
    pulse.set_task_description("fix the bug")
    return pulse, sink


def test_observe_step_end_to_end_hint_on_duplicate():
    pulse, sink = _pulse()
    step = StepObservation(raw_action="open src/a.py", observation="1 line")
    pulse.observe_step(step)   # Lt read recorded
    blind = pulse.observe_action(StepObservation(raw_action="edit src/b.py", host_context={"open_file": "src/b.py"}))
    assert [h.event.type for h in blind] == ["blind_action"]    # b.py never read
    for _ in range(3):
        pulse.observe_step(StepObservation(raw_action="python reproduce.py", observation="AssertionError"))
    kinds = [h.event.type for h in sink.hints]
    assert "duplicate_action" in kinds


def test_done_step_is_skipped_and_history_owned_by_middleware():
    pulse, _ = _pulse()
    assert pulse.observe_step(StepObservation(raw_action="submit", done=True)) == []
    assert pulse.state.total_actions_seen == 0


def test_empty_action_normalized_before_append():
    pulse, _ = _pulse()
    pulse.observe_step(StepObservation(raw_action="   ", observation=""))
    assert pulse.state.actions[0].action.tool == "<empty_action>"
    assert pulse.state.actions[0].label.label == "Emp"


def test_for_swe_repo_preset_wires_defaults():
    from toolpulse.middleware import ToolPulse as TP
    p = TP.for_swe_repo()
    assert isinstance(p.hint_sink, ListSink)


def test_recent_trajectory_drop_last_in_context():
    pulse, sink = _pulse()
    for i in range(4):
        pulse.observe_step(StepObservation(raw_action=f"open f{i}.py", observation=""))
    assert len(pulse.state.actions) == 4


def test_state_wires_detector_stalled_cooldown():
    from toolpulse.detectors.multi_granularity import MultiGranularityDetector

    pulse = ToolPulse(parser=SweAgentParser(), labeler=RepoLabeler("python"),
                      detector=MultiGranularityDetector(stalled_cooldown_steps=5))
    assert pulse.state.last_stalled_step == -5
    pulse.reset()
    assert pulse.state.last_stalled_step == -5


def test_recent_trajectory_drop_last_semantics():
    captured = []

    class SpyRenderer:
        def render(self, events, ctx):
            captured.append(ctx)
            return []

    spy = SpyRenderer()
    pulse = ToolPulse(parser=SweAgentParser(), labeler=RepoLabeler("python"), hint_renderer=spy)
    # 3 identical failing computes: duplicate_action fires on the 3rd -> render is called
    for _ in range(3):
        pulse.observe_step(StepObservation(raw_action="python reproduce.py",
                                           observation="E   AssertionError: assert 1 == 2"))
    assert captured                          # spy render actually ran
    current = pulse.state.actions[-1].step_index
    last = captured[-1]
    indexes = [r.step_index for r in last.recent_trajectory]
    assert current not in indexes            # observe_step ctx drops the just-appended record
    assert indexes == [0, 1]
    # observe_action (pre-execution): ctx.recent_trajectory includes ALL appended records
    captured.clear()
    pulse.observe_action(StepObservation(raw_action="edit unread.py",
                                         host_context={"open_file": "unread.py"}))
    assert captured                          # blind edit on never-read file fired (spy ran)
    assert [r.step_index for r in captured[-1].recent_trajectory] == [0, 1, 2]


def test_openai_isolation_subprocess():
    subprocess.run(
        [sys.executable, "-c", "import toolpulse, sys; assert 'openai' not in sys.modules"],
        check=True,
        cwd=str(Path(__file__).resolve().parents[1]),   # repo root, not pytest invocation dir
    )
