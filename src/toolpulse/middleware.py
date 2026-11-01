# src/toolpulse/middleware.py
"""Composition root: assembles parser/labeler/detector/provider/sink (design §5.3)."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from collections.abc import Sequence
import math

from toolpulse.core.protocols import ActionLabeler, ActionParser, Detector, HintProvider, HintSink
from toolpulse.core.types import (
    Action,
    ActionInspection,
    ActionRecord,
    EMPTY_ACTION_TOOL,
    Hint,
    HintContext,
    StepObservation,
)
from toolpulse.detectors.multi_granularity import MultiGranularityDetector
from toolpulse.hints.assembly import assemble_observation
from toolpulse.hints.sinks import ListSink
from toolpulse.hints.template import TemplateHintProvider
from toolpulse.semantics.generic.labeler import GenericLabeler
from toolpulse.state.session import SessionState

_DEFAULT_STALLED_COOLDOWN_STEPS = 12


class ToolPulse:
    def __init__(self, parser: ActionParser, *, labeler: ActionLabeler | None = None,
                 detector: Detector | None = None, hint_provider: HintProvider | None = None,
                 hint_sink: HintSink | None = None) -> None:
        self.parser = parser
        self.labeler = labeler or GenericLabeler()
        self.detector = detector or MultiGranularityDetector()
        self.hint_provider = hint_provider or TemplateHintProvider()
        self.hint_sink = hint_sink or ListSink(max_hints=getattr(self.detector, "max_history", 500))
        self.task_description = ""
        self._state = self._new_state()

    @classmethod
    def for_swe_repo(cls, language: str = "python", **kwargs) -> "ToolPulse":
        from toolpulse.parsing.sweagent import SweAgentParser
        from toolpulse.semantics.repo.labeler import RepoLabeler
        return cls(parser=SweAgentParser(), labeler=RepoLabeler(language), **kwargs)

    @classmethod
    def for_minimal_react(cls, **kwargs) -> "ToolPulse":
        """Use the minimal framework's JSON protocol and semantic taxonomy."""
        from toolpulse.parsing.minimal_react import MinimalReactParser
        from toolpulse.semantics.minimal_react import MinimalReactLabeler
        return cls(parser=MinimalReactParser(), labeler=MinimalReactLabeler(), **kwargs)

    def _new_state(self) -> SessionState:
        # The fresh session inherits the DETECTOR's stalled cooldown instead of
        # silently the SessionState default (Task 13 review finding).
        return SessionState(
            stalled_cooldown_steps=getattr(
                self.detector, "stalled_cooldown_steps", _DEFAULT_STALLED_COOLDOWN_STEPS
            )
        )

    @property
    def state(self) -> SessionState:
        return self._state

    def reset(self) -> None:
        """Start a new task; external sink destinations remain host-owned."""
        self._state = self._new_state()
        self.task_description = ""
        if isinstance(self.hint_sink, ListSink):
            self.hint_sink.clear()

    def set_task_description(self, description: str | None) -> None:
        self.task_description = description or ""

    @property
    def hints(self) -> list[Hint]:     # convenience for ListSink default
        return getattr(self.hint_sink, "hints", [])

    def assemble_observation(self, observation: str, hints: Sequence[Hint], *,
                             hint_set_name: str | None = None) -> str:
        """Format this batch for the host, defaulting to the provider's hint set."""
        name = hint_set_name if hint_set_name is not None else getattr(
            self.hint_provider, "hint_set_name", "remind_only"
        )
        return assemble_observation(observation, hints, hint_set_name=name)

    def observe_action(self, step: StepObservation) -> list[Hint]:
        """Pre-execution: read-only inspect (blind only). No history append."""
        return self.inspect_action(step).hints

    def inspect_action(self, step: StepObservation) -> ActionInspection:
        """Expose detection events independently of optional hint text for host policies."""
        with self.state.transaction():
            action = self._normalized_action(step)
            info = self.labeler.label(action, step, self.state, record=False)
            events = self.detector.inspect(step, action, info, self.state)
        return ActionInspection(events=events, hints=self._emit(events, step, drop_last=False))

    def observe_step(self, step: StepObservation) -> list[Hint]:
        """Post-execution: canonical order parse → normalize → label → append → analyze (D15)."""
        if step.done:
            return []
        execution_time = float(step.execution_time)
        if not math.isfinite(execution_time) or execution_time < 0:
            raise ValueError("execution_time must be finite and >= 0")
        step = replace(step, execution_time=execution_time)
        with self.state.transaction():
            action = self._normalized_action(step)
            info = self.labeler.label(action, step, self.state, record=True)
            record = ActionRecord(action=action, label=info, step_index=self.state.total_actions_seen,
                                  thought=step.thought, observation=step.observation,
                                  execution_time=step.execution_time)
            self.state.append(record)
            events = self.detector.analyze(step, record, self.state)
        return self._emit(events, step, drop_last=True)

    def _normalized_action(self, step: StepObservation) -> Action:
        action = self.parser.parse(step)
        if not action.raw_action.strip():     # D15: empty-action normalization BEFORE record
            return Action(EMPTY_ACTION_TOOL, {}, "")
        return deepcopy(action)

    def _emit(self, events, step: StepObservation, *, drop_last: bool) -> list[Hint]:
        if not events:
            return []
        ctx = HintContext(task_description=self.task_description, step_observation=step.observation,
                          recent_trajectory=self.state.recent_actions(3, drop_last=drop_last))
        hints = self.hint_provider.provide(events, ctx)
        self.hint_sink.emit(hints, step)
        return hints
