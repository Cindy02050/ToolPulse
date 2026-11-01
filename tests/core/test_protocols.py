# tests/core/test_protocols.py
from typing import Any
from toolpulse.core.protocols import (
    ActionLabeler, ActionParser, ChatClient, Detector, FileTracker, HintProvider,
    HintSink, TrajectoryState,
)
from toolpulse.core.types import Action, ActionRecord, Hint, HintContext, LabelInfo, LabelKind, PulseEvent, StepObservation


class _Files:
    def has_read(self, path: str) -> bool: return False
    def has_edited(self, path: str) -> bool: return False
    def record_read(self, path: str) -> None: ...
    def record_edit(self, path: str) -> None: ...


class _State:
    files: FileTracker
    actions: list[ActionRecord]
    total_actions_seen: int
    score_history: dict[int, list[float]]
    last_stalled_step: int
    reported_stalled_patterns: list[tuple[str, ...]]
    repeated_production_reported: set[tuple[str, ...]]
    features: Any
    grammar: Any
    failures: Any
    def __init__(self) -> None:
        self.files, self.actions, self.total_actions_seen = _Files(), [], 0
        self.score_history, self.last_stalled_step = {}, -12
        self.reported_stalled_patterns, self.repeated_production_reported = [], set()
        self.features = self.grammar = self.failures = object()
    def append(self, record: ActionRecord) -> None: ...
    def trim(self, max_history: int) -> None: ...
    def recent_actions(self, n: int, *, drop_last: bool = False) -> list[ActionRecord]: return []


def test_stub_state_satisfies_trajectory_state_protocol():
    state = _State()
    assert isinstance(state, TrajectoryState)   # runtime protocol check


def test_stub_labeler_signature():
    class L:
        def label(self, action: Action, step: StepObservation, state: TrajectoryState, *, record: bool) -> LabelInfo:
            return LabelInfo(label="G", kind=LabelKind.OTHER)
    assert isinstance(L(), ActionLabeler)


def test_stub_detector_signature_takes_step_and_record():
    class D:
        def inspect(self, step: StepObservation, action: Action, info: LabelInfo, state: TrajectoryState) -> list[PulseEvent]: return []
        def analyze(self, step: StepObservation, record: ActionRecord, state: TrajectoryState) -> list[PulseEvent]: return []
    assert isinstance(D(), Detector)


def test_stub_parser_provider_sink_chat():
    class P:
        def parse(self, step: StepObservation) -> Action: return Action(None, {}, "")
    class R:
        def provide(self, events: list[PulseEvent], ctx: HintContext) -> list[Hint]: return []
    class S:
        def emit(self, hints: list[Hint], step: StepObservation) -> None: ...
    class C:
        def complete(self, prompt: str, *, system: str | None = None) -> str: return ""
    assert isinstance(P(), ActionParser) and isinstance(R(), HintProvider)
    assert isinstance(S(), HintSink) and isinstance(C(), ChatClient)
