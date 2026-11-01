# tests/detectors/test_multi_granularity.py
from toolpulse.core.types import (
    Action, ActionError, ActionRecord, LabelInfo, LabelKind, StepObservation,
)
from toolpulse.detectors.multi_granularity import MultiGranularityDetector
from toolpulse.state.session import SessionState

MG = MultiGranularityDetector(min_pattern_len=3, repeat_times_for_loop=3)


def _step(action_str="cmd", obs=""):
    return StepObservation(raw_action=action_str, observation=obs)


def _rec(tool, args, raw, label, kind, target=None, is_patch=False, is_read=False,
         obs="", error=None):
    return ActionRecord(
        Action(tool, args, raw),
        LabelInfo(label, kind, target, is_patch=is_patch, is_read=is_read,
                  error=error if error is not None else ActionError("none", None)),
        step_index=0, observation=obs)


def _analyze(state, rec, step=None, detector=MG):
    # Middleware appends the record before analyze; unit tests do it themselves.
    state.append(rec)
    return detector.analyze(step or _step(rec.action.raw_action, rec.observation), rec, state)


def test_duplicate_from_third_action_onwards():
    state = SessionState()
    per_step = []
    for _ in range(3):
        rec = _rec("bash-python", "python x.py", "python x.py", "Vp", LabelKind.COMPUTE, obs="ok")
        per_step.append([e.type for e in _analyze(state, rec)])
    assert "duplicate_action" not in per_step[0] + per_step[1]   # first two steps excluded
    assert "duplicate_action" in per_step[2]                     # 3rd identical fires


def test_failed_action_clusters_on_repeat_threshold():
    state = SessionState()
    obs = "Traceback ...\nModuleNotFoundError: No module named 'foo'"
    error = ActionError("import", "ModuleNotFoundError: No module named 'foo'")
    fired = []
    for _ in range(2):   # threshold = 2
        rec = _rec("bash-python", "python x.py", "python x.py", "Ve", LabelKind.COMPUTE,
                   obs=obs, error=error)
        fired += [e.type for e in _analyze(state, rec, _step("python x.py", obs))]
    assert fired.count("failed_action") == 1   # first analyze: cluster count 1, no event; second: fires


def test_operate_clears_failure_clusters():
    state = SessionState()
    obs = "SyntaxError: invalid syntax"
    _analyze(state, _rec("bash-python", "python x.py", "python x.py", "Ve", LabelKind.COMPUTE,
                         obs=obs, error=ActionError("syntax", "SyntaxError: invalid syntax")),
             _step("python x.py", obs))
    _analyze(state, _rec("edit", {"path": "a.py"}, "edit a.py", "P", LabelKind.OPERATE,
                         target="a.py", is_patch=True))
    assert state.failures.clusters == {}


def test_blind_action_via_inspect():
    state = SessionState()
    info = LabelInfo("P", LabelKind.OPERATE, target_file="never/read.py", is_patch=True)
    events = MG.inspect(_step("edit never/read.py"),
                        Action("edit", {"path": "never/read.py"}, "edit never/read.py"), info, state)
    assert [e.type for e in events] == ["blind_action"]


def test_read_recorded_into_file_tracker():
    state = SessionState()
    _analyze(state, _rec("open", {"path": "a.py"}, "open a.py", "Lt", LabelKind.RETRIEVE,
                         target="a.py", is_read=True))
    assert state.files.has_read("a.py")


def test_trim_keeps_counter_but_shrinks_history():
    # Brief erratum: max_history=4 is unconstructible (constructor validation needs
    # max_history >= max(2*max(window_sizes)+1, repeat_times_for_stalled*max(window_sizes)) >= 7
    # for any legal window size); smallest legal config, same intent: counter keeps
    # growing, history shrinks to max_history.
    mg = MultiGranularityDetector(window_sizes=(3,), repeat_times_for_stalled=2, max_history=7)
    state = SessionState()
    for i in range(9):
        _analyze(state, _rec("open", {"path": f"f{i}.py"}, f"open f{i}.py", "Lt",
                             LabelKind.RETRIEVE, target=f"f{i}.py", is_read=True), detector=mg)
    assert state.total_actions_seen == 9 and len(state.actions) == 7


def test_first_two_steps_never_duplicate():
    state = SessionState()
    e1 = _analyze(state, _rec("bash-python", "python x.py", "python x.py", "Vp", LabelKind.COMPUTE))
    e2 = _analyze(state, _rec("bash-python", "python x.py", "python x.py", "Vp", LabelKind.COMPUTE))
    e3 = _analyze(state, _rec("bash-python", "python x.py", "python x.py", "Vp", LabelKind.COMPUTE))
    assert not [e for e in e1 + e2 if e.type == "duplicate_action"]
    assert any(e.type == "duplicate_action" for e in e3)


def test_duplicate_payload_carries_full_action_dict():
    # Legacy parity (verified against MultiGranularityBrain on disk, 2026-10-31):
    # the duplicate event embeds the FULL action dict — tool/args/raw_action/
    # observation/thought/execution_time — not Action.to_dict().
    state = SessionState()
    full = {"tool": "bash-python", "args": "python x.py", "raw_action": "python x.py",
            "observation": "AssertionError: assert 1 == 2", "thought": "run it again",
            "execution_time": 1.5}
    for _ in range(3):
        rec = _rec("bash-python", "python x.py", "python x.py", "Vf", LabelKind.COMPUTE,
                   obs=full["observation"])
        rec = ActionRecord(
            action=rec.action, label=rec.label, step_index=0,
            thought=full["thought"], observation=full["observation"],
            execution_time=full["execution_time"])
        events = _analyze(state, rec, _step("python x.py", full["observation"]))
    dup = [e for e in events if e.type == "duplicate_action"][0]
    assert dup.current == full and dup.previous == full


def test_current_step_equals_total_after_append():
    state = SessionState()
    obs = "Traceback ...\nModuleNotFoundError: No module named 'foo'"
    _analyze(state, _rec("bash-python", "python x.py", "python x.py", "Ve", LabelKind.COMPUTE,
                         obs=obs, error=ActionError("import", "fp-foo")))
    # D15: current_step is the post-append total (legacy used pre-increment + 1)
    assert state.total_actions_seen == 1
    cluster = state.failures.clusters[("bash-python", "import", "fp-foo")]
    assert cluster.last_seen_step == 1 == state.total_actions_seen


def test_grammar_trim_lockstep():
    mg = MultiGranularityDetector(window_sizes=(3,), repeat_times_for_stalled=2, max_history=7)
    state = SessionState()
    for i in range(9):
        _analyze(state, _rec("open", {"path": f"f{i}.py"}, f"open f{i}.py", "Lt",
                             LabelKind.RETRIEVE, target=f"f{i}.py", is_read=True), detector=mg)
        assert len(state.grammar.symbols) == len(state.actions)
    assert state.total_actions_seen == 9
