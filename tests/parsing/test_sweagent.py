from toolpulse.core.types import Action, StepObservation
from toolpulse.parsing.sweagent import SweAgentParser

P = SweAgentParser()


def test_blank_action():
    parsed = P.parse(StepObservation(raw_action="   "))
    assert parsed == Action(None, {}, "")


def test_open_and_goto():
    assert P.parse(StepObservation(raw_action="open src/a.py")).tool == "open"
    assert P.parse(StepObservation(raw_action="goto 10")).tool == "goto"


def test_str_replace_editor_args():
    a = P.parse(StepObservation(raw_action="str_replace_editor command=str_replace path=src/a.py"))
    # legacy parity quirk: command = parts[1] verbatim ("command=" prefix kept)
    assert a.tool == "str_replace_editor" and a.args["command"] == "command=str_replace"


def test_legacy_edit_uses_host_context_open_file():
    step = StepObservation(raw_action="edit x", host_context={"open_file": "src/a.py"})
    assert P.parse(step).args == {"path": "src/a.py"}


def test_cd_chain_takes_last_segment():
    a = P.parse(StepObservation(raw_action="cd /repo && grep -rn foo ."))
    assert a.tool == "bash-grep"
    # legacy parity: truncation affects tool/args extraction ONLY — raw_action
    # is always the full stripped original (ToolFamiliar._action_from_step).
    assert a.raw_action == "cd /repo && grep -rn foo ."
    assert a.args == "grep -rn foo ."


def test_cd_chain_empty_tail_keeps_full_raw_action():
    a = P.parse(StepObservation(raw_action="cd /repo &&"))
    assert a.tool == "cd" and a.args == {} and a.raw_action == "cd /repo &&"


def test_timeout_bash_first_word():
    a = P.parse(StepObservation(raw_action="timeout 10 python reproduce.py"))
    assert a.tool == "bash-python" and a.args == "python reproduce.py"


def test_cd_form_vs_bare_duplicate_identity_matches_legacy():
    # Regression (2026-10-31 final review): raw_action keeps the full string, so the cd
    # form and the bare command are DIFFERENT actions for duplicate identity.
    # Verified on the legacy brain from disk: `cd /repo && python x.py` once,
    # then `python x.py` ×3 → the duplicate fires ONLY on the 3rd bare call
    # (i.e. NOT at the step right after the cd form — with ×2 bare calls it
    # never fires, because the cd form breaks the 3-in-a-row identity).
    from toolpulse.detectors.multi_granularity import MultiGranularityDetector
    from toolpulse.middleware import ToolPulse
    from toolpulse.hints.sinks import ListSink
    from toolpulse.semantics.repo.labeler import RepoLabeler

    pulse = ToolPulse(parser=P, labeler=RepoLabeler("python"),
                      detector=MultiGranularityDetector(offline=True), hint_sink=ListSink())
    stream = ["cd /repo && python x.py", "python x.py", "python x.py"]
    fired = []
    for raw in stream:
        n = len(pulse.hint_sink.hints)
        pulse.observe_step(StepObservation(raw_action=raw, observation=""))
        fired.append([h.event.type for h in pulse.hint_sink.hints[n:]])
    assert "duplicate_action" not in fired[0] + fired[1] + fired[2]   # never, incl. right after the cd form
    pulse2 = ToolPulse(parser=P, labeler=RepoLabeler("python"),
                       detector=MultiGranularityDetector(offline=True), hint_sink=ListSink())
    stream = ["cd /repo && python x.py", "python x.py", "python x.py", "python x.py"]
    fired = []
    for raw in stream:
        n = len(pulse2.hint_sink.hints)
        pulse2.observe_step(StepObservation(raw_action=raw, observation=""))
        fired.append([h.event.type for h in pulse2.hint_sink.hints[n:]])
    assert "duplicate_action" not in fired[0] + fired[1] + fired[2]   # cd form breaks the run
    assert "duplicate_action" in fired[3]                  # 3rd bare python x.py, matching legacy
