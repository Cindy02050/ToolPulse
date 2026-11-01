# tests/parity/generate_eventful_golden.py
"""Freeze an EVENTFUL synthetic golden: legacy brain vs ToolPulse, full-payload parity.

Run from /root/OmniCode/ToolPulse:
    python tests/parity/generate_eventful_golden.py

The two real-trajectory fixtures (sweagenttestrepo / pydicom) fire ZERO events
on their step streams, so nothing currently freezes an end-to-end event
payload.  This generator builds a deterministic 24-step eventful stream, replays
it through BOTH the legacy brain (from disk, offline=True) and ToolPulse
(MultiGranularityDetector(offline=True) + SessionState(stalled_cooldown_steps=12)
via the middleware), asserts EQUALITY of the per-step event streams (full
payload dicts) and freezes the stream + events to
``fixtures/eventful_synthetic.json`` (schema: {"steps": [{raw_action,
observation, thought, execution_time}...], "events": [[...event dicts...] per
step]}).

Stream tuning note (deviation from the task brief's example triple, verified on
the legacy brain before freezing): the brief's ``["open", "edit", "pytest"] x8``
cycle fires loop_action and stalled_action but can NEVER fire failed_action —
every ``edit`` carries label P (OPERATE), and the OPERATE branch clears the
failure clusters before the next cycle's pytest can reach the repeat threshold.
The tuned cycle is ``["open", "pytest-fail", "pytest-fail"] x8`` (24 steps,
3-periodic): it fires all three — failed_action (2nd failing run of each cycle
reaches threshold 2), loop_action (grammar compresses the Lb/Vf/Vf period),
stalled_action (identical feature windows) — while keeping the brief's shape
(one read + two validation runs per cycle, stable traceback).

Detector/brain config is IDENTICAL on both sides: window_sizes=(3,),
repeat_times_for_loop=3, repeat_times_for_stalled=3, min_actions_before_stalled=3,
stalled_cooldown_steps=12, max_history=50, offline=True.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

SWE = "/root/OmniCode/SWE-agent"
OUT = Path(__file__).parent / "fixtures" / "eventful_synthetic.json"

DETECTOR_CONFIG = dict(
    window_sizes=(3,),
    repeat_times_for_loop=3,
    repeat_times_for_stalled=3,
    min_actions_before_stalled=3,
    stalled_cooldown_steps=12,
    max_history=50,
    offline=True,
)

TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "tests/test_a.py", line 3, in test_add\n'
    "    assert add(1, 1) == 3\n"
    "E   AssertionError: assert 1 == 2\n"
    "=========================== 1 failed in 0.05s ============================"
)


def build_steps() -> list[dict]:
    steps = []
    for _ in range(8):
        steps.append({"raw_action": "open src/a.py",
                      "observation": "1: def add(a, b):\n2:     return a - b",
                      "thought": "look at the source", "execution_time": 0.4})
        steps.append({"raw_action": "timeout 30 python -m pytest tests/test_a.py",
                      "observation": TRACEBACK,
                      "thought": "run the tests", "execution_time": 2.1})
        steps.append({"raw_action": "timeout 30 python -m pytest tests/test_a.py",
                      "observation": TRACEBACK,
                      "thought": "run the tests again", "execution_time": 2.0})
    return steps


def legacy_events(steps) -> list[list[dict]]:
    """Drive the legacy brain exactly as ToolFamiliar.observe_step would."""
    sys.path.insert(0, SWE)
    from sweagent.agent.algorithm.multi_granularity import MultiGranularityBrain
    from sweagent.agent.tool_familiar import parse_action

    brain = MultiGranularityBrain(**DETECTOR_CONFIG)
    out = []
    for step in steps:
        raw = step["raw_action"].strip()
        action = {"tool": None, "args": {}, "raw_action": raw,
                  "observation": step["observation"], "thought": step["thought"],
                  "execution_time": step["execution_time"]}
        tool, args = parse_action(raw, None)
        action.update(tool=tool, args=args)
        out.append(brain.analyze(action))
    return out


def toolpulse_events(steps) -> list[list[dict]]:
    """Replay the same steps through ToolPulse with the identical config."""
    from toolpulse.core.types import StepObservation
    from toolpulse.detectors.multi_granularity import MultiGranularityDetector
    from toolpulse.hints.sinks import ListSink
    from toolpulse.middleware import ToolPulse
    from toolpulse.parsing.sweagent import SweAgentParser
    from toolpulse.semantics.repo.labeler import RepoLabeler

    pulse = ToolPulse(
        parser=SweAgentParser(), labeler=RepoLabeler("python"),
        detector=MultiGranularityDetector(**DETECTOR_CONFIG), hint_sink=ListSink())
    # middleware._new_state() wires SessionState(stalled_cooldown_steps=12)
    # from the detector; assert it so the golden cannot silently drift.
    assert pulse.state.last_stalled_step == -12
    out = []
    for step in steps:
        n = len(pulse.hint_sink.hints)
        pulse.observe_step(StepObservation(**step))
        out.append([h.event.to_dict() for h in pulse.hint_sink.hints[n:]])
    return out


def main() -> None:
    steps = build_steps()
    legacy = legacy_events(steps)
    ours = toolpulse_events(steps)

    mismatches = [
        (i, leg, our) for i, (leg, our) in enumerate(zip(legacy, ours)) if leg != our
    ]
    if mismatches:
        print("BLOCKED: legacy vs ToolPulse event streams differ")
        for i, leg, our in mismatches:
            print(f"  step {i}:\n    legacy:    {json.dumps(leg, default=str)}\n"
                  f"    toolpulse: {json.dumps(our, default=str)}")
        sys.exit(1)

    counts = Counter(e["type"] for step in ours for e in step)
    required = {"failed_action", "loop_action", "stalled_action"}
    missing = required - set(counts)
    if missing:
        print(f"BLOCKED: eventful golden is not eventful enough, missing {missing}")
        sys.exit(1)

    OUT.write_text(json.dumps({"steps": steps, "events": ours},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: {len(steps)} steps, events {dict(counts)} -> {OUT}")


if __name__ == "__main__":
    main()
