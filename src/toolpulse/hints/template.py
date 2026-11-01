# src/toolpulse/hints/template.py
"""Template-based hint renderer — the default ``HintRenderer`` implementation.

Port of legacy ``sweagent/agent/tool_familiar_hints.py`` lines 24-112
(``ToolFamiliarHintRenderer`` → ``TemplateHintRenderer``): the ``_render_event``
branch structure is preserved verbatim; events are ``PulseEvent`` objects
(serialized via ``to_dict()``) and rendered texts are wrapped as ``Hint``s.
"""
from __future__ import annotations

import importlib.resources
from functools import lru_cache
from typing import Any

import yaml

from toolpulse.core.types import Hint, HintContext, PulseEvent

DEFAULT_HINT_SET = "remind_only"
HINTS_RESOURCE = "toolpulse.resources/hints.yaml"


@lru_cache(maxsize=1)
def load_hint_sets() -> dict[str, Any]:
    data = yaml.safe_load(
        importlib.resources.files("toolpulse.resources").joinpath("hints.yaml").read_text()
    ) or {}
    hint_sets = data.get("hint_sets")
    if not isinstance(hint_sets, dict):
        message = f"TemplateHintRenderer hint config must define a 'hint_sets' mapping: {HINTS_RESOURCE}"
        raise ValueError(message)
    return hint_sets


class TemplateHintRenderer:
    """Render structured ToolPulse events with externally configured hint text."""

    def __init__(self, hint_sets: dict[str, Any] | None = None,
                 hint_set_name: str = DEFAULT_HINT_SET) -> None:
        self.hint_sets = hint_sets if hint_sets is not None else load_hint_sets()
        self.hint_set_name = hint_set_name

    def render(self, events: list[PulseEvent], ctx: HintContext) -> list[Hint]:
        hint_set = self._hint_set(self.hint_set_name)
        hints: list[Hint] = []

        for event in events:
            text = self._render_event(event.to_dict(), hint_set)
            if text:
                hints.append(Hint(event=event, text=text))

        return hints

    def _hint_set(self, hint_set_name: str | None) -> dict[str, Any]:
        name = hint_set_name or DEFAULT_HINT_SET
        hint_set = self.hint_sets.get(name)
        if hint_set is None:
            known = ", ".join(sorted(self.hint_sets))
            message = f"Unknown hint set {name!r}. Known hint sets: {known}"
            raise ValueError(message)
        if not isinstance(hint_set, dict):
            message = f"Hint set {name!r} must be a mapping"
            raise ValueError(message)
        return hint_set

    def _render_event(self, event: dict[str, Any], hint_set: dict[str, Any]) -> str | None:
        event_type = event.get("type")
        if event_type == "duplicate_action":
            return self._render_duplicate_action(event, hint_set)
        if event_type == "failed_action":
            return self._render_template(hint_set.get("failed_action"), self._context(event))
        if event_type == "loop_action":
            return self._render_template(hint_set.get("loop_action"), self._context(event))
        if event_type == "stalled_action":
            return self._render_template(hint_set.get("stalled_action"), self._context(event))
        if event_type == "blind_action":
            return self._render_template(hint_set.get("blind_action"), self._context(event))
        if event_type == "macro_candidate":
            return self._render_macro_candidate(event, hint_set)
        return None

    def _render_duplicate_action(self, event: dict[str, Any], hint_set: dict[str, Any]) -> str | None:
        templates = hint_set.get("duplicate_action")
        if not isinstance(templates, dict):
            return None

        current = event.get("current") or {}
        template_key = "empty" if not current.get("raw_action") else "normal"
        context = self._context(event)
        context.update(
            {
                "tool": current.get("tool"),
                "args": current.get("args"),
            }
        )
        return self._render_template(templates.get(template_key), context)

    def _render_macro_candidate(self, event: dict[str, Any], hint_set: dict[str, Any]) -> str | None:
        template_config = hint_set.get("macro_candidate")
        context = self._context(event)

        if isinstance(template_config, dict):
            workflow_kinds = template_config.get("workflow_kinds") or {}
            workflow_kind = event.get("workflow_kind")
            context["workflow_text"] = workflow_kinds.get(
                workflow_kind,
                template_config.get("default_workflow_text", "approximately similar workflows"),
            )
            return self._render_template(template_config.get("template"), context)

        return self._render_template(template_config, context)

    @staticmethod
    def _context(event: dict[str, Any]) -> dict[str, Any]:
        pattern = event.get("pattern") or []
        return {
            **event,
            "pattern_text": " -> ".join(str(item) for item in pattern),
        }

    @staticmethod
    def _render_template(template: Any, context: dict[str, Any]) -> str | None:
        if not isinstance(template, str):
            return None
        return template.format(**context)
