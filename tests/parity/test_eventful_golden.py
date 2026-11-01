# tests/parity/test_eventful_golden.py
"""Replay the frozen EVENTFUL synthetic golden through ToolPulse.

The fixture is produced by ``generate_eventful_golden.py`` (run manually), which
verified per-step full-payload EQUALITY against the legacy brain from disk
before freezing.  This test needs no legacy environment: it replays the frozen
steps through ToolPulse with exactly the generator's configuration and asserts
the per-step event streams equal the frozen golden.
"""
import json
from pathlib import Path

from toolpulse.core.types import StepObservation
from toolpulse.detectors.multi_granularity import MultiGranularityDetector
from toolpulse.hints.sinks import ListSink
from toolpulse.middleware import ToolPulse
from toolpulse.parsing.sweagent import SweAgentParser
from toolpulse.semantics.repo.labeler import RepoLabeler

FIXTURE = Path(__file__).parent / "fixtures" / "eventful_synthetic.json"

# Keep in sync with generate_eventful_golden.DETECTOR_CONFIG.
DETECTOR_CONFIG = dict(
    window_sizes=(3,),
    repeat_times_for_loop=3,
    repeat_times_for_stalled=3,
    min_actions_before_stalled=3,
    stalled_cooldown_steps=12,
    max_history=50,
    offline=True,
)


def _replay(steps):
    pulse = ToolPulse(parser=SweAgentParser(), labeler=RepoLabeler("python"),
                      detector=MultiGranularityDetector(**DETECTOR_CONFIG),
                      hint_sink=ListSink())
    per_step = []
    for step in steps:
        n = len(pulse.hint_sink.hints)
        pulse.observe_step(StepObservation(**step))
        per_step.append([h.event.to_dict() for h in pulse.hint_sink.hints[n:]])
    return per_step


def test_eventful_golden_replays_identically():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    per_step = _replay(data["steps"])
    for i, (fired, golden) in enumerate(zip(per_step, data["events"])):
        assert fired == golden, f"step {i}: eventful golden broken"


def test_eventful_golden_actually_fires_all_three_types():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    types = {e["type"] for step in data["events"] for e in step}
    assert {"failed_action", "loop_action", "stalled_action"} <= types
    assert len(data["steps"]) == 24
