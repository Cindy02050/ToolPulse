# src/toolpulse/core/types.py
"""Data shapes for ToolPulse. Zero third-party dependencies (design §5.1)."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Mapping

EMPTY_ACTION_TOOL = "<empty_action>"


class LabelKind(Enum):
    RETRIEVE = "retrieve"   # Ls/Lt/Lb
    OPERATE = "operate"     # E/P/Ps/Pi/Pr — progress signal
    COMPUTE = "compute"     # Vp/Vf/Ve — outcome in LabelInfo.error
    OTHER = "other"         # G/Emp incl. former-SKIP actions (D13)


@dataclass(frozen=True)
class Action:
    tool: str | None          # None = empty action; bash actions "bash-<first-word>"
    args: Any                 # dict (structured tools) or str (bash command body)
    raw_action: str

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": deepcopy(self.args), "raw_action": self.raw_action}


@dataclass
class StepObservation:
    raw_action: str
    thought: str = ""
    observation: str = ""
    execution_time: float = 0.0
    done: bool = False
    host_context: Mapping[str, Any] | None = None   # opaque host context (D: rename from state)


@dataclass(frozen=True)
class ActionError:
    kind: str                 # "none"/"syntax"/"import"/"test_failure"/"runtime"
    fingerprint: str | None   # observation error fingerprint for failed-clustering


_NO_ERROR = ActionError(kind="none", fingerprint=None)


@dataclass(frozen=True)
class LabelInfo:
    label: str                # refined label, taxonomy-specific (e.g. "Ps"); feeds grammar & display
    kind: LabelKind
    target_file: str | None = None
    is_patch: bool = False
    is_create: bool = False
    is_read: bool = False     # establishes "has read file" knowledge (D19)
    error: ActionError = _NO_ERROR


@dataclass(frozen=True)
class ActionRecord:
    action: Action            # empty action already normalized (D15)
    label: LabelInfo
    step_index: int
    thought: str = ""
    observation: str = ""
    execution_time: float = 0.0


@dataclass(frozen=True)
class RawFeaturesRow:
    thought_length: float
    tool_hash: tuple[float, ...]   # 16-dim, stdlib tuple; numpy lives in state layer
    args_hash: tuple[float, ...]
    observation_length: float
    execution_time: float
    has_error: bool


@dataclass(frozen=True)
class PulseEvent:
    """Base class; concrete events mirror legacy event dict fields exactly (design §5.1)."""
    type: ClassVar[str]

    def to_dict(self) -> dict[str, Any]:
        import dataclasses
        return {"type": self.type, **dataclasses.asdict(self)}


@dataclass(frozen=True)
class DuplicateActionEvent(PulseEvent):
    type: ClassVar[str] = "duplicate_action"
    current: dict[str, Any]
    previous: dict[str, Any]


@dataclass(frozen=True)
class FailedActionEvent(PulseEvent):
    type: ClassVar[str] = "failed_action"
    error_type: str
    tool: str
    error_fingerprint: str | None
    repeat_times: int


@dataclass(frozen=True)
class LoopActionEvent(PulseEvent):
    type: ClassVar[str] = "loop_action"
    production: str
    repeat_times: int
    pattern: list[str]


@dataclass(frozen=True)
class StalledActionEvent(PulseEvent):
    type: ClassVar[str] = "stalled_action"
    production: int
    repeat_times: int
    pattern: list[str]
    score: float
    window_starts: list[int]
    representative_start: int
    representative_actions: list[str]


@dataclass(frozen=True)
class BlindActionEvent(PulseEvent):
    type: ClassVar[str] = "blind_action"
    tool: str | None
    path: str | None
    raw_action: str


@dataclass(frozen=True)
class Hint:
    event: PulseEvent
    text: str


@dataclass(frozen=True)
class ActionInspection:
    """Pre-execution events survive even if a renderer produces no hints."""
    events: list[PulseEvent]
    hints: list[Hint]


@dataclass
class HintContext:
    task_description: str
    step_observation: str
    recent_trajectory: list[ActionRecord] = field(default_factory=list)


# --- Failure clustering shapes (moved here from state/failures.py, 2026-10-31 final review revision) ---
# Pure data shared by the state layer (FailureTable) and the detector; living in
# core keeps the detector's import D8-clean (detectors must not import state).
FailureSignature = tuple[str, str, str]   # (tool, error_type, fingerprint)


@dataclass
class FailureCluster:
    count: int
    last_seen_step: int


# --- Semantic label display vocabulary (moved here from semantics/repo/labeler.py) ---
# This table is the repo-taxonomy's display vocabulary, kept in core as part of
# the shared label contract (design §7, 2026-10-31 final review revision): detectors render
# loop patterns through it without a lateral detectors→semantics import.
# Unknown labels pass through unchanged.
SEMANTIC_LABEL_DISPLAY: dict[str, str] = {
    "Emp": "empty action",
    "Ls": "search",
    "Lt": "targeted read",
    "Lb": "browse whole file",
    "P": "edit",
    "Ps": "edit with syntax error",
    "Pi": "edit with import error",
    "Pr": "re-edit file",
    "Vp": "test run with no error",
    "Vf": "test run with failure",
    "Ve": "test run with error",
    "E": "environment setup",
    "G": "general / other",
}


def semantic_pattern_display(pattern: tuple[str, ...]) -> list[str]:
    """Return human-readable text for each semantic label in a pattern."""
    return [SEMANTIC_LABEL_DISPLAY.get(label, label) for label in pattern]
