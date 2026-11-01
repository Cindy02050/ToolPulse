# src/toolpulse/core/protocols.py
"""Behavior contracts. Zero third-party dependencies (design §5.2, D18/D19/D20)."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from toolpulse.core.types import (
    Action, ActionRecord, Hint, HintContext, LabelInfo, PulseEvent, StepObservation,
)


@runtime_checkable
class ActionParser(Protocol):
    def parse(self, step: StepObservation) -> Action:
        """Blank action -> Action(None, {}, "").

        Malformed structured host payloads may raise ValueError before any
        action is executed or detection state is committed.
        """
        ...


@runtime_checkable
class FileTracker(Protocol):
    def has_read(self, path: str) -> bool: ...
    def has_edited(self, path: str) -> bool: ...
    def record_read(self, path: str) -> None: ...
    def record_edit(self, path: str) -> None: ...


@runtime_checkable
class TrajectoryState(Protocol):
    """Detection blackboard contract (D20); state.SessionState is the reference impl.

    Heavy sections are Any by design: features = FeatureStore (numpy rows/matrix/window),
    grammar = GrammarState (sksequitur feed/current_grammar), failures = FailureTable.
    """
    files: FileTracker
    actions: list[ActionRecord]
    total_actions_seen: int          # never decreases on trim (legacy semantics)
    score_history: dict[int, list[float]]
    last_stalled_step: int
    reported_stalled_patterns: list[tuple[str, ...]]
    repeated_production_reported: set[tuple[str, ...]]
    features: Any
    grammar: Any
    failures: Any

    def append(self, record: ActionRecord) -> None:
        """Atomic: append record + increment total_actions_seen (D15)."""
        ...

    def trim(self, max_history: int) -> None:
        """Atomic: shrink records/feature rows/grammar symbols in lockstep + rebuild parser (D15)."""
        ...

    def recent_actions(self, n: int, *, drop_last: bool = False) -> list[ActionRecord]: ...


@runtime_checkable
class ActionLabeler(Protocol):
    def label(self, action: Action, step: StepObservation, state: TrajectoryState,
              *, record: bool) -> LabelInfo:
        """record=False: pre-execution inspect (read-only, no record_edit).
        record=True: post-execution (P* actions call files.record_edit)."""
        ...


@runtime_checkable
class Detector(Protocol):
    # step is required: featurizer reads thought/observation/execution_time (D18)
    def inspect(self, step: StepObservation, action: Action, info: LabelInfo,
                state: TrajectoryState) -> list[PulseEvent]: ...
    def analyze(self, step: StepObservation, record: ActionRecord,
                state: TrajectoryState) -> list[PulseEvent]: ...


@runtime_checkable
class HintProvider(Protocol):
    """Provide hints for detected events using the current execution context."""

    def provide(self, events: list[PulseEvent], ctx: HintContext) -> list[Hint]: ...


@runtime_checkable
class HintSink(Protocol):
    def emit(self, hints: list[Hint], step: StepObservation) -> None:
        """Delivery channel only — NOT injection (D21)."""
        ...


@runtime_checkable
class ChatClient(Protocol):
    def complete(self, prompt: str, *, system: str | None = None) -> str: ...
