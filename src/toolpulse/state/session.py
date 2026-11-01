# src/toolpulse/state/session.py
from __future__ import annotations

import dataclasses
import math
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Iterator

from toolpulse.core.types import Action, ActionError, ActionRecord, LabelInfo, LabelKind, RawFeaturesRow
from toolpulse.state.failures import FailureTable
from toolpulse.state.features import FeatureStore
from toolpulse.state.files import FileStateTracker
from toolpulse.state.grammar import GrammarState


def _label_kind_of(value: str) -> LabelKind:
    return LabelKind(value)


def _row_of(d: dict) -> RawFeaturesRow:
    return RawFeaturesRow(**{k: tuple(v) if isinstance(v, list) else v for k, v in d.items()})


class SessionState:
    """The single home of all mutable detection state (design §5.4, D6/D15)."""

    def __init__(self, *, stalled_cooldown_steps: int = 12) -> None:
        self.files = FileStateTracker()
        self.actions: list[ActionRecord] = []
        self.features = FeatureStore()
        self.grammar = GrammarState()
        self.failures = FailureTable()
        self.total_actions_seen = 0
        self.score_history: dict[int, list[float]] = {}
        self.last_stalled_step = -stalled_cooldown_steps
        self.reported_stalled_patterns: list[tuple[str, ...]] = []
        self.repeated_production_reported: set[tuple[str, ...]] = set()

    def append(self, record: ActionRecord) -> None:
        self.actions.append(record)
        self.total_actions_seen += 1   # atomic with the append (D15)

    def trim(self, max_history: int) -> None:
        overflow = len(self.actions) - max_history
        if overflow <= 0:
            return
        del self.actions[:overflow]
        self.features.trim(overflow)
        self.grammar.trim(overflow)   # atomic lockstep, mirrors legacy _trim_history

    def recent_actions(self, n: int, *, drop_last: bool = False) -> list[ActionRecord]:
        actions = self.actions
        if drop_last and actions:
            actions = actions[:-1]
        return actions[-n:]

    def snapshot(self) -> dict[str, Any]:
        return {
            "actions": [
                {
                    "action": r.action.to_dict(),
                    "label": {**dataclasses.asdict(r.label),
                              "kind": r.label.kind.value,
                              "error": dataclasses.asdict(r.label.error)},
                    "step_index": r.step_index,
                    "thought": r.thought, "observation": r.observation,
                    "execution_time": r.execution_time,
                }
                for r in self.actions
            ],
            "raw_rows": [dataclasses.asdict(row) for row in self.features.rows],
            "grammar_symbols": self.grammar.snapshot(),
            "failures": self.failures.snapshot(),
            "files": self.files.snapshot(),
            "total_actions_seen": self.total_actions_seen,
            "score_history": {k: list(v) for k, v in self.score_history.items()},
            "last_stalled_step": self.last_stalled_step,
            "reported_stalled_patterns": [list(p) for p in self.reported_stalled_patterns],
            "repeated_production_reported": [list(p) for p in self.repeated_production_reported],
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Load into a temporary session so rejected snapshots leave us intact."""
        restored = SessionState()
        restored._load_snapshot(deepcopy(data))
        restored._validate_restored_state()
        self.__dict__.update(restored.__dict__)

    def _validate_restored_state(self) -> None:
        if type(self.total_actions_seen) is not int or self.total_actions_seen < len(self.actions):
            raise ValueError("snapshot total_actions_seen must be an integer >= retained action count")
        if any(not isinstance(symbol, str) for symbol in self.grammar.symbols):
            raise ValueError("snapshot grammar symbols must be strings")
        # Empty derived sections are allowed for custom detectors that do not use
        # features/grammar. Populated sections must refer to the same actions.
        for section in (self.features.rows, self.grammar.symbols):
            if section and len(section) != len(self.actions):
                raise ValueError("snapshot derived history must align with actions")
        for record in self.actions:
            if (type(record.step_index) is not int or not 0 <= record.step_index < self.total_actions_seen
                    or not isinstance(record.action.raw_action, str)):
                raise ValueError("snapshot action index or raw_action is invalid")
            if (not isinstance(record.execution_time, (int, float))
                    or not math.isfinite(record.execution_time) or record.execution_time < 0):
                raise ValueError("snapshot execution_time must be finite and >= 0")
        for row in self.features.rows:
            if len(row.tool_hash) != 16 or len(row.args_hash) != 16:
                raise ValueError("snapshot feature hashes must each have 16 dimensions")
            values = (*row.tool_hash, *row.args_hash, row.thought_length,
                      row.observation_length, row.execution_time)
            if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
                raise ValueError("snapshot features must be finite numbers")

    def _load_snapshot(self, data: dict[str, Any]) -> None:
        for r in data["actions"]:
            label = LabelInfo(
                label=r["label"]["label"], kind=_label_kind_of(r["label"]["kind"]),
                target_file=r["label"]["target_file"], is_patch=r["label"]["is_patch"],
                is_create=r["label"]["is_create"], is_read=r["label"]["is_read"],
                error=ActionError(r["label"]["error"]["kind"], r["label"]["error"]["fingerprint"]),
            )
            self.actions.append(ActionRecord(
                action=Action(r["action"]["tool"], r["action"]["args"], r["action"]["raw_action"]),
                label=label, step_index=r["step_index"], thought=r["thought"],
                observation=r["observation"], execution_time=r["execution_time"]))
        for row in data["raw_rows"]:
            self.features.append_row(_row_of(row))
        self.grammar.restore(data["grammar_symbols"])
        self.failures.restore(data["failures"])
        self.files.restore(data["files"])
        self.total_actions_seen = data["total_actions_seen"]
        self.score_history = {int(k): list(v) for k, v in data["score_history"].items()}
        self.last_stalled_step = data["last_stalled_step"]
        self.reported_stalled_patterns = [tuple(p) for p in data["reported_stalled_patterns"]]
        self.repeated_production_reported = {tuple(p) for p in data["repeated_production_reported"]}

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Roll back a failed detection update, including the derived matrix.

        Rendering and delivery belong outside this boundary: an external sink
        may already have delivered a hint when it raises.
        """
        checkpoint = self.snapshot()
        matrix = [row.copy() for row in self.features.matrix]
        try:
            yield
        except BaseException:
            self.restore(checkpoint)
            self.features.set_matrix(matrix)
            raise
