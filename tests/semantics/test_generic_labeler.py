from toolpulse.core.types import Action, LabelKind, StepObservation
from toolpulse.semantics.generic.labeler import GenericLabeler

G = GenericLabeler({"read_file": LabelKind.RETRIEVE, "python": LabelKind.COMPUTE})

def test_known_tool_maps_and_label_is_tool_name():
    info = G.label(Action("read_file", {"path": "a"}, "read_file a"), StepObservation(raw_action="read_file a"), None, record=True)
    assert info.kind is LabelKind.RETRIEVE and info.label == "read_file"

def test_unknown_tool_defaults_to_other():
    info = G.label(Action("dance", {}, "dance"), StepObservation(raw_action="dance"), None, record=False)
    assert info.kind is LabelKind.OTHER and info.label == "dance"

def test_no_side_channels():
    info = G.label(Action("python", "print(1)", "python -c 'print(1)'"),
                   StepObservation(raw_action="x", observation="boom"), None, record=True)
    assert info.error.kind == "none" and not (info.is_patch or info.is_read or info.is_create)
