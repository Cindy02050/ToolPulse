from toolpulse.core.types import FailedActionEvent, HintContext
from toolpulse.hints.template import TemplateHintRenderer

SETS = {"remind_only": {
    "failed_action": "The command failed with {error_type}. Check whether previous edits broke it.",
    "duplicate_action": {"normal": "You repeated {tool}.", "empty": "Empty action again."},
}}

def test_failed_action_template_render():
    r = TemplateHintRenderer(hint_sets=SETS)
    ev = FailedActionEvent(error_type="import", tool="bash-python", error_fingerprint="f", repeat_times=2)
    hints = r.render([ev], HintContext(task_description="", step_observation="obs"))
    assert len(hints) == 1 and hints[0].text == "The command failed with import. Check whether previous edits broke it."

def test_unknown_event_type_renders_nothing():
    r = TemplateHintRenderer(hint_sets=SETS)
    assert r.render([], HintContext("", "")) == []
