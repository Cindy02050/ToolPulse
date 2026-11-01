# tests/state/test_session.py
from toolpulse.core.protocols import TrajectoryState
from toolpulse.core.types import (
    Action, ActionError, ActionRecord, LabelInfo, LabelKind, RawFeaturesRow,
)
from toolpulse.state.session import SessionState


def _record(i: int, label: str = "Lt", kind: LabelKind = LabelKind.RETRIEVE) -> ActionRecord:
    return ActionRecord(action=Action("open", {"path": f"f{i}.py"}, f"open f{i}.py"),
                        label=LabelInfo(label, kind, target_file=f"f{i}.py", is_read=True),
                        step_index=i)


def test_satisfies_protocol_and_append_is_atomic():
    s = SessionState()
    assert isinstance(s, TrajectoryState)
    s.append(_record(0)); s.append(_record(1))
    assert s.total_actions_seen == 2 and len(s.actions) == 2


def test_trim_is_atomic_across_sections():
    s = SessionState()
    for i in range(5):
        s.append(_record(i)); s.grammar.feed("Lt"); s.features.append_row(
            RawFeaturesRow(0.0, (0.0,) * 16, (0.0,) * 16, 0.0, 0.0, False))
    s.trim(1)   # keep 1
    assert len(s.actions) == 1 and len(s.features.rows) == 1 and len(s.grammar.symbols) == 1
    assert s.total_actions_seen == 5   # counter never trimmed (D15 invariant)


def test_recent_actions_drop_last():
    s = SessionState()
    for i in range(4):
        s.append(_record(i))
    assert [r.step_index for r in s.recent_actions(3)] == [1, 2, 3]
    assert [r.step_index for r in s.recent_actions(3, drop_last=True)] == [0, 1, 2]


def test_snapshot_restore_roundtrip_preserves_everything_but_matrix():
    s = SessionState()
    s.append(_record(0, "P", LabelKind.OPERATE)); s.grammar.feed("P")
    s.files.record_read("a.py"); s.last_stalled_step = 7; s.score_history[3] = [0.1]
    snap = s.snapshot()
    s2 = SessionState(); s2.restore(snap)
    assert s2.total_actions_seen == 1 and s2.last_stalled_step == 7
    assert s2.grammar.symbols == ["P"] and s2.files.has_read("a.py")
    assert s2.actions[0].label.label == "P" and s2.score_history == {3: [0.1]}
    assert s2.features.matrix == []   # rebuilt by next analyze (design §5.4)


def test_snapshot_is_point_in_time_for_score_history():
    s = SessionState()
    s.score_history[3] = [0.1, 0.2]
    snap = s.snapshot()
    s.score_history[3].append(9.9)
    s.score_history[5] = [1.0]
    assert snap["score_history"] == {3: [0.1, 0.2]}   # snapshot unchanged by later mutation
    s2 = SessionState()
    s2.restore(snap)
    s2.score_history[3].append(7.7)
    assert snap["score_history"] == {3: [0.1, 0.2]}   # restored session does not alias snapshot
