import json

import pytest

from toolpulse import StepObservation, ToolPulse
from toolpulse.parsing.minimal_react import MinimalReactParser


def test_json_action_preserves_values_and_original_text():
    raw = json.dumps({"tool": "file", "args": {"mode": "write", "path": "a b.txt", "content": "hello\n世界"}})
    action = MinimalReactParser().parse(StepObservation(raw_action=raw))
    assert action.tool == "file"
    assert action.args == {"mode": "write", "path": "a b.txt", "content": "hello\n世界"}
    assert action.raw_action == raw


def test_blank_action():
    action = MinimalReactParser().parse(StepObservation(raw_action="  "))
    assert action.tool is None and action.args == {} and action.raw_action == ""


@pytest.mark.parametrize("payload", [
    "not json", "[]", '{}', '{"tool":"unknown","args":{}}',
    '{"tool":"file","args":{"mode":"delete","path":"a"}}',
    '{"tool":"file","args":{"mode":"write","path":"a"}}',
    '{"tool":"file","args":{"mode":"read","path":""}}',
    '{"tool":"check","args":{"path":"a","expected":3}}',
])
def test_invalid_proposal_is_rejected_without_recording(payload):
    pulse = ToolPulse.for_minimal_react()
    with pytest.raises(ValueError):
        pulse.inspect_action(StepObservation(raw_action=payload))
    assert pulse.state.total_actions_seen == 0
