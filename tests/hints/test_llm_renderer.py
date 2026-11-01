from toolpulse.core.types import FailedActionEvent, HintContext
from toolpulse.hints.llm import LLMHintRenderer
from toolpulse.llm.stub import StubChatClient

HINT_SET = {"system_prompt": "sys", "events": {
    "failed_action": {"prompt": "Event {error_type} on {tool}; observation: {observation}; task: {task_description}"}}}

def test_renders_via_chat_client_with_prompt_context():
    r = LLMHintRenderer(HINT_SET, StubChatClient(["fix it"]))
    ev = FailedActionEvent("import", "bash-python", "f", 2)
    hints = r.render([ev], HintContext(task_description="T", step_observation="boom"))
    assert hints[0].text == "fix it" and "import" in r.client.calls[0]["prompt"]

def test_fail_soft_drops_event_on_client_error():
    class Boom:
        def complete(self, prompt, *, system=None):
            raise RuntimeError("down")
    r = LLMHintRenderer(HINT_SET, Boom())
    assert r.render([FailedActionEvent("import", "bash-python", "f", 2)], HintContext("T", "o")) == []

def test_offline_stub_hint():
    r = LLMHintRenderer(HINT_SET, StubChatClient(), offline=True)
    hints = r.render([FailedActionEvent("import", "bash-python", "f", 2)], HintContext("T", "o"))
    assert hints[0].text == "[llm-hint stub:failed_action]"


# Shaped like the production llm_coach entry in SWE-agent's
# config/tool_familiar_hints.yaml: master_template with
# {{TASK_DESCRIPTION}}/{{RECENT_TRAJECTORY}}/{{METADATA}} tokens +
# behavior_description leaves (leaf tokens filled from the event).
MASTER_HINT_SET = {
    "system_prompt": "You are an experienced software developer.",
    "master_template": (
        "Software engineering task:\n{{TASK_DESCRIPTION}}\n\n"
        "Observed tool-use behavior:\n{{BEHAVIOR_DESCRIPTION}}\n\n"
        "Relevant behavior details:\n{{METADATA}}\n\n"
        "Recent work trajectory:\n{{RECENT_TRAJECTORY}}"
    ),
    "events": {
        "failed_action": {
            "behavior_description": "The agent received {{ERROR_TYPE}} error again from {{TOOL}}.",
            "metadata_fields": ["error_type", "tool", "error_fingerprint", "observation"],
        },
    },
}

def test_master_template_prompt_fills_task_metadata_and_wraps_response():
    stub = StubChatClient(["Tool-use notice: repeated import failure.\nRecommended action: check the import path."])
    r = LLMHintRenderer(MASTER_HINT_SET, stub)
    ev = FailedActionEvent("import", "bash-python", "fp-1", 2)
    hints = r.render([ev], HintContext(task_description="Fix the failing import in utils.py",
                                        step_observation="ModuleNotFoundError: No module named 'utils'"))
    assert len(stub.calls) == 1
    prompt = stub.calls[0]["prompt"]
    assert stub.calls[0]["system"] == "You are an experienced software developer."
    assert "Fix the failing import in utils.py" in prompt                    # filled TASK_DESCRIPTION
    assert '"error_type": "import"' in prompt and '"tool": "bash-python"' in prompt   # event metadata (METADATA)
    assert "ModuleNotFoundError: No module named 'utils'" in prompt          # triggering observation in METADATA
    assert "The agent received import error again from bash-python." in prompt  # BEHAVIOR_DESCRIPTION leaf tokens filled
    assert "Recent work trajectory:" in prompt                               # RECENT_TRAJECTORY block present
    assert len(hints) == 1 and hints[0].event is ev
    assert hints[0].text == "Tool-use notice: repeated import failure.\nRecommended action: check the import path."
