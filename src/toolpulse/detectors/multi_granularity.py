# src/toolpulse/detectors/multi_granularity.py
"""Multi-granularity detector: duplicate / failed / loop / stalled / blind rules.

Port of legacy ``sweagent/agent/algorithm/multi_granularity.py``
(``MultiGranularityBrain``, lines 35-456) onto the ``TrajectoryState``
protocol. Per D8 this module imports nothing from ``toolpulse.state`` — every
piece of mutable detection state is reached through the ``state`` object.

Adaptations vs legacy (behaviour-preserving except where marked):

- ``analyze(step, record, state)`` replaces ``analyze(action)``: middleware has
  already appended the record (D15), so the duplicate guard is
  ``len(state.actions) < 3`` (current = ``[-1]``) and the failed-cluster
  ``current_step`` is the post-append ``state.total_actions_seen`` (legacy
  checked the pre-append history and used ``total_actions_seen + 1``).
- ``inspect(step, action, info, state)`` keeps the blind rule only; legacy
  ``inspect`` additionally skipped SKIP and normalized Emp actions, which the
  labeler/middleware now own (D13/D15).
- read recording uses ``LabelInfo.is_read`` instead of the Lt/Lb/create labels
  (D19); the blind rule uses ``is_patch`` / ``is_create`` the same way.
- the failed-action rule derives everything from ``LabelInfo.error`` — the
  labeler's adjusted single error channel (D14). Legacy's extra
  ``not action.get("has_error", False)`` conjunct in the per-tool prune is
  deleted (it was always true in real legacy runs; registered divergence
  D14). The fingerprint comes precomputed from the labeler.
- ``reset()`` / ``snapshot()`` / ``_trim_history()`` / Emp normalization are
  gone: middleware swaps in a fresh session state, ``SessionState`` owns the
  snapshot, and ``state.trim`` owns the history cut.
- ``score_history`` is not pre-seeded per window size (legacy ``reset()``
  seeded it); this detector creates each window's list on first append, which
  yields the identical content.
- ``FailureCluster`` / ``FailureSignature`` live in ``core.types`` (2026-10-31
  final review revision, D9 consolidation): D8 forbids importing them from
  ``toolpulse.state.failures``, and the failure table consumes cluster values
  structurally (``count`` / ``last_seen_step`` attribute access in
  expire/prune/snapshot).
- ``semantic_pattern_display`` is likewise imported from ``core.types`` (the
  repo-taxonomy's display vocabulary is part of the shared label contract;
  design §7 2026-10-31 final review revision) — no lateral detectors→semantics import.
- the duplicate event serializes the FULL action dict from the stored records
  (``tool``/``args``/``raw_action``/``observation``/``thought``/
  ``execution_time``), matching the legacy payload verbatim — not
  ``Action.to_dict()`` (2026-10-31 final review revision).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from sksequitur import Production

from toolpulse.core.protocols import TrajectoryState
from toolpulse.core.types import (
    Action,
    ActionRecord,
    BlindActionEvent,
    DuplicateActionEvent,
    FailedActionEvent,
    FailureCluster,
    FailureSignature,
    LabelInfo,
    LabelKind,
    LoopActionEvent,
    PulseEvent,
    StalledActionEvent,
    StepObservation,
    semantic_pattern_display,
)
from toolpulse.detectors.featurizer import FeatureWeights, StepFeaturizer

Pattern = tuple[str, ...]


def _record_action_dict(record: ActionRecord) -> dict[str, Any]:
    """Serialize a record the way the legacy duplicate event carried its actions.

    Legacy ``ToolFamiliar._action_from_step`` built the full action dict
    (tool/args/raw_action/observation/thought/execution_time) and
    ``_check_exact_duplicate_action`` embedded it verbatim in the event.
    """
    action = record.action
    return {
        "tool": action.tool,
        "args": action.args,
        "raw_action": action.raw_action,
        "observation": record.observation,
        "thought": record.thought,
        "execution_time": record.execution_time,
    }


class MultiGranularityDetector:
    """Detect repeated tool-use patterns with hybrid algorithm."""

    def __init__(
        self,
        min_pattern_len: int = 3,
        repeat_times_for_loop: int = 3,
        failed_action_repeat_threshold: int = 2,
        failed_action_window_steps: int = 8,
        window_sizes: tuple[int, ...] = (3, 5, 8),
        repeat_times_for_stalled: int = 3,
        stalled_distance_threshold: float = 1.10,
        min_actions_before_stalled: int = 15,
        stalled_cooldown_steps: int = 12,
        stalled_pattern_similarity_suppression: float = 0.67,
        max_history: int = 500,
        weights: FeatureWeights | None = None,
        offline: bool = False,
        language: str = "python",
    ) -> None:
        integer_options = {
            "min_pattern_len": min_pattern_len,
            "repeat_times_for_loop": repeat_times_for_loop,
            "failed_action_repeat_threshold": failed_action_repeat_threshold,
            "failed_action_window_steps": failed_action_window_steps,
            "repeat_times_for_stalled": repeat_times_for_stalled,
            "min_actions_before_stalled": min_actions_before_stalled,
            "stalled_cooldown_steps": stalled_cooldown_steps,
            "max_history": max_history,
        }
        for name, value in integer_options.items():
            if type(value) is not int:
                raise ValueError(f"{name} must be an integer")
        if min_pattern_len < 1:
            raise ValueError("min_pattern_len must be >= 1")
        if not isinstance(window_sizes, (tuple, list)) or any(type(size) is not int for size in window_sizes):
            raise ValueError("window_sizes must contain integers >= 3")
        if (not isinstance(stalled_distance_threshold, (int, float))
                or not math.isfinite(stalled_distance_threshold) or stalled_distance_threshold < 0):
            raise ValueError("stalled_distance_threshold must be finite and >= 0")
        if repeat_times_for_loop < 2:
            message = "repeat_times_for_loop must be >= 2"
            raise ValueError(message)
        if failed_action_repeat_threshold < 1:
            message = "failed_action_repeat_threshold must be >= 1"
            raise ValueError(message)
        if failed_action_window_steps < 1:
            message = "failed_action_window_steps must be >= 1"
            raise ValueError(message)
        if not window_sizes or any(size < 3 for size in window_sizes):
            message = "window_sizes must contain integers >= 3"
            raise ValueError(message)
        if repeat_times_for_stalled < 2:
            message = "repeat_times_for_stalled must be >= 2"
            raise ValueError(message)
        if min_actions_before_stalled < 0:
            message = "min_actions_before_stalled must be >= 0"
            raise ValueError(message)
        if stalled_cooldown_steps < 0:
            message = "stalled_cooldown_steps must be >= 0"
            raise ValueError(message)
        if not 0.0 <= stalled_pattern_similarity_suppression <= 1.0:
            message = "stalled_pattern_similarity_suppression must be between 0 and 1"
            raise ValueError(message)
        required_history = max(
            2 * max(window_sizes) + 1,
            repeat_times_for_stalled * max(window_sizes),
        )
        if max_history < required_history:
            message = f"max_history must be >= {required_history} for the configured windows"
            raise ValueError(message)

        self.min_pattern_len = min_pattern_len
        self.repeat_times_for_loop = repeat_times_for_loop
        self.failed_action_repeat_threshold = failed_action_repeat_threshold
        self.failed_action_window_steps = failed_action_window_steps
        self.window_sizes = tuple(sorted(set(window_sizes)))
        self.repeat_times_for_stalled = repeat_times_for_stalled
        self.stalled_distance_threshold = stalled_distance_threshold
        self.min_actions_before_stalled = min_actions_before_stalled
        self.stalled_cooldown_steps = stalled_cooldown_steps
        self.stalled_pattern_similarity_suppression = stalled_pattern_similarity_suppression
        self.max_history = max_history
        self.offline = offline
        self.language = language   # kept for parity of the constructor surface; not used in detection
        self.featurizer = StepFeaturizer(weights)

    def inspect(
        self,
        step: StepObservation,
        action: Action,
        info: LabelInfo,
        state: TrajectoryState,
    ) -> list[PulseEvent]:
        """Inspect a proposed action without updating detector state (blind rule only)."""
        if not (
            info.is_patch
            and not info.is_create
            and info.target_file
            and not state.files.has_read(info.target_file)
        ):
            return []
        return [BlindActionEvent(tool=action.tool, path=info.target_file, raw_action=action.raw_action)]

    def analyze(
        self,
        step: StepObservation,
        record: ActionRecord,
        state: TrajectoryState,
    ) -> list[PulseEvent]:
        """Analyze one already-appended record and return structured events."""
        info, action = record.label, record.action
        events: list[PulseEvent] = []

        if self._check_exact_duplicate(state):                     # guard len(state.actions) < 3 (D15)
            events.append(self._duplicate_event(state))
        if info.is_read and info.target_file:                      # D19: is_read replaces Lt/Lb/create
            state.files.record_read(info.target_file)
        failed = self._maybe_failed_action(record, state)          # current_step = post-append total (D15)
        if failed:
            events.append(failed)
        state.grammar.feed(info.label)
        has_error = info.error.kind != "none"                      # D14: single derived channel
        state.features.append_row(self.featurizer.extract(
            thought=step.thought or record.thought,
            tool=str(action.tool or "UNKNOWN"),
            args=action.args if action.args != {} and action.args != "" else {},
            observation=step.observation or record.observation,
            execution_time=step.execution_time or record.execution_time,
            has_error=has_error))
        state.trim(self.max_history)                               # atomic cut at the legacy _trim_history call site
        state.features.set_matrix(self.featurizer.transform_history(state.features.rows))

        loop = self._check_tail_repeated_production(state)
        if loop:
            events.append(loop)

        profiles = self._update_current_profiles(state)
        stalled = self._maybe_detect_tail_stalled(profiles, state)
        if stalled:
            events.append(stalled)

        return events

    def _check_exact_duplicate(self, state: TrajectoryState) -> bool:
        if len(state.actions) < 3:
            return False

        current = state.actions[-1].action
        previous = state.actions[-2].action
        before_previous = state.actions[-3].action
        current_identity = self._action_identity(current)
        return (
            self._action_identity(previous) == current_identity
            and self._action_identity(before_previous) == current_identity
        )

    def _duplicate_event(self, state: TrajectoryState) -> DuplicateActionEvent:
        # Full record dicts, matching the legacy payload (not Action.to_dict(),
        # which drops observation/thought/execution_time).
        return DuplicateActionEvent(
            current=_record_action_dict(state.actions[-1]),
            previous=_record_action_dict(state.actions[-2]),
        )

    @staticmethod
    def _action_identity(action: Action) -> tuple[Any, Any, Any]:
        return (
            action.tool,
            action.args,
            action.raw_action,
        )

    def _maybe_failed_action(
        self,
        record: ActionRecord,
        state: TrajectoryState,
    ) -> FailedActionEvent | None:
        info = record.label
        tool = str(record.action.tool)
        current_step = state.total_actions_seen
        state.failures.expire(current_step, self.failed_action_window_steps)

        if info.kind is LabelKind.OPERATE:
            state.failures.clear()
        elif info.kind is LabelKind.COMPUTE and info.error.kind == "none":
            state.failures.prune_by_tool(tool)

        if info.error.kind == "none":
            return None

        fingerprint = info.error.fingerprint
        if fingerprint is None:
            return None

        signature: FailureSignature = (tool, info.error.kind, fingerprint)
        clusters = state.failures.clusters
        previous = clusters.get(signature)
        cluster = FailureCluster(
            count=1 if previous is None else previous.count + 1,
            last_seen_step=current_step,
        )
        if cluster.count < self.failed_action_repeat_threshold:
            clusters[signature] = cluster
            return None

        clusters.pop(signature, None)
        return FailedActionEvent(
            error_type=info.error.kind,
            tool=tool,
            error_fingerprint=fingerprint,
            repeat_times=self.failed_action_repeat_threshold,
        )

    def _check_tail_repeated_production(self, state: TrajectoryState) -> LoopActionEvent | None:
        grammar = state.grammar.current_grammar()
        start_body = grammar[Production(0)]

        if len(start_body) < self.repeat_times_for_loop:
            return None

        tail = start_body[-self.repeat_times_for_loop :]

        if not all(isinstance(item, Production) for item in tail):
            return None

        if len(set(tail)) != 1:
            return None

        repeated_prod = tail[0]
        pattern = tuple(grammar.expand(repeated_prod))

        if len(pattern) < self.min_pattern_len:
            return None

        if self._is_single_label_repetition(pattern):
            return None

        if not self.offline and pattern in state.repeated_production_reported:
            return None
        if not self.offline:
            state.repeated_production_reported.add(pattern)

        return LoopActionEvent(
            production=str(repeated_prod),
            repeat_times=self.repeat_times_for_loop,
            pattern=semantic_pattern_display(pattern),
        )

    def _update_current_profiles(self, state: TrajectoryState) -> dict[int, tuple[float, int]]:
        profiles: dict[int, tuple[float, int]] = {}
        count = len(state.features)
        for size in self.window_sizes:
            current_start = count - size
            if current_start < size:
                continue

            distances = [
                (self._window_distance(state, start, current_start, size), start)
                for start in range(current_start - size + 1)
            ]
            profile_value, nearest_start = min(distances)
            profiles[size] = (profile_value, nearest_start)
            state.score_history.setdefault(size, []).append(profile_value)
            del state.score_history[size][:-self.max_history]
        return profiles

    def _maybe_detect_tail_stalled(
        self,
        profiles: dict[int, tuple[float, int]],
        state: TrajectoryState,
    ) -> StalledActionEvent | None:
        candidates: list[tuple[float, int, Pattern]] = []
        count = len(state.features)
        if state.total_actions_seen < self.min_actions_before_stalled:
            return None

        for size in self.window_sizes:
            required = size * self.repeat_times_for_stalled
            if count < required or size not in profiles:
                continue

            starts = [count - required + offset * size for offset in range(self.repeat_times_for_stalled)]
            distances = [
                self._window_distance(state, starts[left], starts[right], size)
                for left in range(self.repeat_times_for_stalled)
                for right in range(left + 1, self.repeat_times_for_stalled)
            ]
            stalled_score = max(distances)
            if stalled_score > self.stalled_distance_threshold:
                continue

            pattern = tuple(
                state.actions[index].action.tool or ""
                for index in range(starts[-1], starts[-1] + size)
            )
            candidates.append((stalled_score, size, pattern))

        if not candidates:
            return None

        score, size, pattern = min(candidates, key=lambda item: (item[1], item[0]))
        current_step = len(state.features)
        if not self.offline and state.total_actions_seen - state.last_stalled_step < self.stalled_cooldown_steps:
            return None
        if not self.offline and any(
            self._sequence_similarity(pattern, previous) >= self.stalled_pattern_similarity_suppression
            for previous in state.reported_stalled_patterns
        ):
            return None

        required = size * self.repeat_times_for_stalled
        starts = [current_step - required + offset * size for offset in range(self.repeat_times_for_stalled)]
        representative_start = self._window_medoid(state, starts, size)
        pattern = tuple(
            state.actions[index].action.tool or ""
            for index in range(representative_start, representative_start + size)
        )
        if not self.offline:
            state.last_stalled_step = state.total_actions_seen
            state.reported_stalled_patterns.append(pattern)
        return StalledActionEvent(
            production=size,
            repeat_times=self.repeat_times_for_stalled,
            pattern=list(pattern),
            score=score,
            window_starts=starts,
            representative_start=representative_start,
            representative_actions=[
                state.actions[index].action.raw_action
                for index in range(representative_start, representative_start + size)
            ],
        )

    def _window_distance(self, state: TrajectoryState, left: int, right: int, size: int) -> float:
        left_window = state.features.window(left, size)
        right_window = state.features.window(right, size)
        return float(np.linalg.norm(left_window - right_window) / math.sqrt(size))

    def _window_medoid(self, state: TrajectoryState, starts: list[int], size: int) -> int:
        return min(
            starts,
            key=lambda candidate: sum(
                self._window_distance(state, candidate, other, size) for other in starts if other != candidate
            ),
        )

    def _sequence_similarity(self, left: Pattern, right: Pattern) -> float:
        distance = self._levenshtein_distance(list(left), list(right))
        return 1.0 - distance / max(len(left), len(right), 1)

    @staticmethod
    def _levenshtein_distance(left: list[str], right: list[str]) -> int:
        previous = list(range(len(right) + 1))
        for left_index, left_value in enumerate(left, start=1):
            current = [left_index]
            for right_index, right_value in enumerate(right, start=1):
                current.append(
                    min(
                        current[-1] + 1,
                        previous[right_index] + 1,
                        previous[right_index - 1] + int(left_value != right_value),
                    )
                )
            previous = current
        return previous[-1]

    @staticmethod
    def _is_single_label_repetition(pattern: tuple[str, ...]) -> bool:
        return len(set(pattern)) == 1
