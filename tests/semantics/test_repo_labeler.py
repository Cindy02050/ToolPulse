from toolpulse.core.types import Action, LabelKind, StepObservation
from toolpulse.semantics.repo.labeler import KIND_OF_LABEL, RepoLabeler
from tests.semantics._state_stub import StubState


L = RepoLabeler()
S = StubState()

def test_kind_mapping_table_is_total_over_legacy_labels():
    assert KIND_OF_LABEL == {
        "Ls": LabelKind.RETRIEVE, "Lt": LabelKind.RETRIEVE, "Lb": LabelKind.RETRIEVE,
        "E": LabelKind.OPERATE, "P": LabelKind.OPERATE, "Ps": LabelKind.OPERATE,
        "Pi": LabelKind.OPERATE, "Pr": LabelKind.OPERATE,
        "Vp": LabelKind.COMPUTE, "Vf": LabelKind.COMPUTE, "Ve": LabelKind.COMPUTE,
        "G": LabelKind.OTHER, "Emp": LabelKind.OTHER,
    }

def test_former_skip_actions_now_other_and_enter_sequence():
    info = L.label(Action("bash-cd", "cd /repo", "cd /repo"), StepObservation(raw_action="cd /repo"), S, record=True)
    assert info.label == "G" and info.kind is LabelKind.OTHER     # D13

def test_read_and_create_flags():
    info = L.label(Action("open", {"path": "a.py"}, "open a.py"), StepObservation(raw_action="open a.py"), S, record=True)
    assert info.label == "Lb" and info.is_read   # legacy: open -> "Lb"; read recording is detector-side (D19)
    info2 = L.label(Action("create", {"path": "b.py"}, "create b.py"), StepObservation(raw_action="create b.py"), S, record=True)
    assert info2.is_create and info2.is_read

def test_patch_records_edit_and_pr_on_repatch():
    L.label(Action("create", {"path": "c.py"}, "create c.py"), StepObservation(raw_action="create c.py"), S, record=False)  # inspect: create must not mark c.py edited
    first = L.label(Action("edit", {"path": "c.py"}, "edit x"), StepObservation(raw_action="edit x"), S, record=True)
    assert first.label == "P" and first.is_patch and S.files.last_edit == "c.py"
    second = L.label(Action("edit", {"path": "c.py"}, "edit x"), StepObservation(raw_action="edit x"), S, record=True)
    assert second.label == "Pr"          # re-edit detection via files.has_edited

def test_compute_error_enrichment_single_channel():
    a = Action("bash-pytest", "pytest -q", "pytest -q")
    step = StepObservation(raw_action="pytest -q", observation="FAILED test_a::test_x - assert 1 == 2")
    info = L.label(a, step, S, record=True)
    assert info.kind is LabelKind.COMPUTE and info.error.kind == "test_failure"   # Vf path

def test_record_false_has_no_side_effects():
    before = (set(S.files.edited), set(S.files.read))
    L.label(Action("edit", {"path": "z.py"}, "edit z"), StepObservation(raw_action="edit z"), S, record=False)
    assert (set(S.files.edited), set(S.files.read)) == before
