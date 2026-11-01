import json
from pathlib import Path
import runpy

import pytest

from toolpulse import StepObservation, TemplateHintRenderer, ToolPulse


@pytest.mark.parametrize("hint_set", ["remind_only", "different_message_type"])
def test_complete_demo_records_execution_and_delivers_feedback(hint_set, capsys):
    example = runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples/minimal_react/run.py"))
    pulse = ToolPulse.for_minimal_react(hint_renderer=TemplateHintRenderer(hint_set_name=hint_set))
    # A reused pulse must not carry actions or hints into a new task.
    pulse.observe_step(StepObservation(raw_action='{"tool":"check","args":{"path":"old","expected":"x"}}',
                                      observation='{"ok":true}'))
    history = example["run"](pulse)
    assert pulse.state.total_actions_seen == 7
    assert [r.label.label for r in pulse.state.actions] == [
        "write", "read", "check_failed", "check_failed", "check_failed", "write", "check_ok",
    ]
    assert {h.event.type for h in pulse.hints} >= {"blind_action", "failed_action", "duplicate_action"}
    observations = [m["content"] for m in history if m["role"] == "user"][1:]
    assert len(observations) == 7
    if hint_set == "different_message_type":
        decoded = [json.loads(value) for value in observations]
        assert decoded[0]["hint"] and decoded[3]["hint"] and decoded[4]["hint"]
        assert json.loads(decoded[-1]["observation"])["ok"] is True
    else:
        assert "<tool_pulse>" in observations[0]
        assert "<tool_pulse>" in observations[3]
        assert "<tool_pulse>" in observations[4]
        assert json.loads(observations[-1])["ok"] is True
    assert not pulse.state.failures.clusters
    assert "Finished" in capsys.readouterr().out


def test_demo_step_budget(capsys):
    example = runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples/minimal_react/run.py"))
    pulse = ToolPulse.for_minimal_react()
    example["run"](pulse, max_steps=2)
    assert pulse.state.total_actions_seen == 2
    assert "Step limit" in capsys.readouterr().out
