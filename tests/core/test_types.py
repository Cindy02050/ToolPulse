# tests/core/test_types.py
from toolpulse.core.types import (
    Action, ActionError, ActionRecord, BlindActionEvent, DuplicateActionEvent,
    FailedActionEvent, Hint, HintContext, LabelInfo, LabelKind, LoopActionEvent,
    PulseEvent, RawFeaturesRow, StalledActionEvent, StepObservation, EMPTY_ACTION_TOOL,
)

def test_label_kind_has_exactly_four_members():
    assert {k.name for k in LabelKind} == {"RETRIEVE", "OPERATE", "COMPUTE", "OTHER"}

def test_step_observation_defaults():
    step = StepObservation(raw_action="open file.py")
    assert (step.thought, step.observation, step.execution_time, step.done, step.host_context) == ("", "", 0.0, False, None)

def test_event_to_dict_roundtrip_shape():
    ev = FailedActionEvent(error_type="import", tool="bash-python", error_fingerprint="f1", repeat_times=2)
    d = ev.to_dict()
    assert d["type"] == "failed_action" and d["error_type"] == "import" and d["repeat_times"] == 2

def test_duplicate_event_uses_plain_dict_actions():
    ev = DuplicateActionEvent(current={"tool": "bash-python", "args": "python x.py", "raw_action": "python x.py"},
                              previous={"tool": "bash-python", "args": "python x.py", "raw_action": "python x.py"})
    assert ev.to_dict()["current"]["tool"] == "bash-python"

def test_label_info_defaults():
    info = LabelInfo(label="G", kind=LabelKind.OTHER)
    assert info.error == ActionError(kind="none", fingerprint=None)
    assert not (info.is_patch or info.is_create or info.is_read)

def test_raw_features_row_is_stdlib():
    row = RawFeaturesRow(thought_length=1.0, tool_hash=(0.1,) * 16, args_hash=(0.2,) * 16,
                         observation_length=3.0, execution_time=0.5, has_error=False)
    assert len(row.tool_hash) == 16 and isinstance(row.tool_hash, tuple)
