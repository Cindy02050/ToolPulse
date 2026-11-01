import json

from toolpulse import LabelKind, StepObservation, ToolPulse
from toolpulse.semantics.minimal_react import KIND_OF_LABEL, MinimalReactLabeler


def step(tool, args, result=None):
    return StepObservation(raw_action=json.dumps({"tool": tool, "args": args}),
                           observation="" if result is None else json.dumps(result))


def test_blind_edit_pre_is_read_only_then_read_removes_warning():
    pulse = ToolPulse.for_minimal_react()
    assert isinstance(pulse.labeler, MinimalReactLabeler)
    edit = step("file", {"mode": "write", "path": "note.txt", "content": "ready"})
    pre = pulse.inspect_action(edit)
    assert [event.type for event in pre.events] == ["blind_action"]
    assert not pulse.state.files.has_edited("note.txt")
    assert pulse.state.total_actions_seen == 0
    pulse.observe_step(step("file", {"mode": "read", "path": "note.txt"}, {"ok": True, "content": "old"}))
    assert pulse.state.files.has_read("note.txt")
    assert pulse.inspect_action(edit).events == []
    edit.observation = json.dumps({"ok": True})
    pulse.observe_step(edit)
    assert pulse.state.files.has_edited("note.txt")
    assert [r.label.kind for r in pulse.state.actions] == [LabelKind.RETRIEVE, LabelKind.OPERATE]
    assert KIND_OF_LABEL["write"] is LabelKind.OPERATE


def test_check_failures_cluster_and_success_clears_them():
    pulse = ToolPulse.for_minimal_react()
    args = {"path": "note.txt", "expected": "ready"}
    failure = step("check", args, {"ok": False, "error": "expected ready, got broken"})
    assert pulse.observe_step(failure) == []
    info = pulse.state.actions[-1].label
    assert info.label == "check_failed" and info.kind is LabelKind.COMPUTE
    assert info.error.kind == "test_failure" and info.error.fingerprint
    hints = pulse.observe_step(failure)
    assert [h.event.type for h in hints] == ["failed_action"]
    pulse.observe_step(failure)
    assert pulse.state.failures.clusters
    pulse.observe_step(step("check", args, {"ok": True}))
    assert pulse.state.actions[-1].label.label == "check_ok"
    assert not pulse.state.failures.clusters


def test_unsuccessful_read_does_not_establish_file_knowledge():
    pulse = ToolPulse.for_minimal_react()
    pulse.observe_step(step("file", {"mode": "read", "path": "missing"}, {"ok": False, "error": "missing file"}))
    assert not pulse.state.files.has_read("missing")
    assert pulse.state.actions[-1].label.error.kind == "runtime"
