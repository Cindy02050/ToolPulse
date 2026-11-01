# src/toolpulse/hints/llm.py
"""LLM-backed hint renderer — the ``llm_coach`` ``HintRenderer`` implementation.

Port of legacy ``sweagent/agent/algorithm/utils/llm_hint_builder.py`` lines 1-139
(``LLMHintBuilder`` → ``LLMHintRenderer``): the per-event fail-soft loop, the
master-prompt pipeline (``{{BEHAVIOR_DESCRIPTION}}``/``{{COACHING_POLICY}}``/
``{{TASK_DESCRIPTION}}``/``{{RECENT_TRAJECTORY}}``/``{{METADATA}}`` + leaf
tokens) and the trajectory serialization with its ``_TRAJECTORY_FIELD_LIMIT``
truncation are preserved verbatim. Differences (by design): the chat backend is
an injected ``ChatClient`` (never imported here), the prompt-dump switch is the
``dump_prompts`` constructor parameter instead of an environment variable
(D11), events are ``PulseEvent`` objects (serialized via ``to_dict()``), the
triggering step's observation is folded in via the legacy caller's
``setdefault`` semantics, and rendered texts are wrapped as ``Hint``s. Entries
may alternatively carry a ``prompt`` format template filled from the flat
context (event fields + ``observation``/``task_description``/``recent_trajectory``).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from toolpulse.core.protocols import ChatClient
from toolpulse.core.types import ActionRecord, Hint, HintContext, PulseEvent

logger = logging.getLogger(__name__)

_TRAJECTORY_FIELD_LIMIT = 500


class LLMHintRenderer:
    """Render llm_coach hints by filling the master prompt template and calling an LLM."""

    def __init__(self, hint_set: dict[str, Any], client: ChatClient, *,
                 offline: bool = False, dump_prompts: bool = False) -> None:
        self.hint_set = hint_set
        self.client = client
        self.offline = offline
        self.dump_prompts = dump_prompts

    def render(self, events: list[PulseEvent], ctx: HintContext) -> list[Hint]:
        hints: list[Hint] = []
        events_map = self.hint_set.get("events", {}) or {}
        for event in events:
            event_dict = event.to_dict()
            entry = events_map.get(event_dict.get("type"))
            if entry is None:
                continue
            if self.offline:
                if self.dump_prompts:
                    self._render_and_maybe_dump(event_dict, entry, ctx)
                hints.append(Hint(event=event, text=f"[llm-hint stub:{event_dict.get('type')}]"))
                continue
            try:
                prompt = self._render_and_maybe_dump(event_dict, entry, ctx)
                text = self.client.complete(prompt, system=self.hint_set.get("system_prompt"))
                if not isinstance(text, str):
                    raise TypeError("ChatClient.complete must return a string")
                text = text.strip()
            except Exception as exc:  # noqa: BLE001 - fail-soft: drop this event's hint
                logger.warning("llm hint failed for %s: %s", event_dict.get("type"), exc)
                continue
            if not text:
                continue
            hints.append(Hint(event=event, text=text))
        return hints

    def _render_and_maybe_dump(
        self,
        event: dict[str, Any],
        entry: dict[str, Any],
        ctx: HintContext,
    ) -> str:
        prompt = self._render_prompt(event, entry, ctx)
        if self.dump_prompts:
            logger.info("llm hint prompt for %s:\n%s", event.get("type"), prompt)
        return prompt

    def _render_prompt(
        self,
        event: dict[str, Any],
        entry: dict[str, Any],
        ctx: HintContext,
    ) -> str:
        # Legacy caller did event.setdefault("observation", step.observation) so the
        # llm_coach builder can expose the triggering step's observation in METADATA.
        event.setdefault("observation", ctx.step_observation or "")
        template: Any = entry.get("prompt")
        if isinstance(template, str) and template:
            return template.format(**self._context(event, ctx))
        master: str = self.hint_set.get("master_template", "")
        # Phase 1: insert behavior/coaching (their text still contains leaf tokens).
        prompt = master.replace("{{BEHAVIOR_DESCRIPTION}}", entry.get("behavior_description", ""))
        prompt = prompt.replace("{{COACHING_POLICY}}", entry.get("coaching_policy", ""))
        # Phase 2: fill master scalar tokens.
        prompt = prompt.replace("{{TASK_DESCRIPTION}}", ctx.task_description or "")
        prompt = prompt.replace("{{RECENT_TRAJECTORY}}", self._serialize_trajectory(ctx.recent_trajectory))
        prompt = prompt.replace("{{METADATA}}", self._serialize_metadata(event, entry.get("metadata_fields")))
        # Phase 2b: fill leaf tokens from the event.
        for token, value in self._leaf_values(event).items():
            prompt = prompt.replace("{{" + token + "}}", value)
        return prompt

    @staticmethod
    def _context(event: dict[str, Any], ctx: HintContext) -> dict[str, Any]:
        return {
            **event,
            "task_description": ctx.task_description or "",
            "recent_trajectory": LLMHintRenderer._serialize_trajectory(ctx.recent_trajectory),
        }

    @staticmethod
    def _leaf_values(event: dict[str, Any]) -> dict[str, str]:
        etype = event.get("type")
        values: dict[str, str] = {}
        if etype == "duplicate_action":
            current = event.get("current") or {}
            values["TOOL"] = str(current.get("tool"))
        elif etype == "failed_action":
            values["ERROR_TYPE"] = str(event.get("error_type"))
            values["TOOL"] = str(event.get("tool"))
        elif etype == "blind_action":
            values["PATH"] = str(event.get("path"))
            values["TOOL"] = str(event.get("tool"))
        elif etype == "loop_action":
            values["PATTERN"] = str(event.get("pattern"))
            values["REPEAT_TIMES"] = str(event.get("repeat_times"))
        elif etype == "stalled_action":
            values["SIZE"] = str(event.get("production"))
        return values

    @staticmethod
    def _serialize_trajectory(recent_trajectory: list[ActionRecord]) -> str:
        if not recent_trajectory:
            return "(no prior tool-use steps before the current action.)"
        steps = [
            {
                "raw_action": record.action.raw_action or "",
                "thought": record.thought or "",
                "observation": record.observation or "",
            }
            for record in recent_trajectory
        ]
        count = len(steps)
        noun = "step" if count == 1 else "steps"
        blocks: list[str] = [
            f"The {count} tool-use {noun} immediately before the current action (oldest to newest):"
        ]
        for index, action in enumerate(steps):
            # index 0 is the oldest shown -> farthest back; the last one immediately precedes the current action.
            offset = count - index
            if offset == 1:
                label = "1 step before current (immediately preceding step)"
            else:
                label = f"{offset} steps before current"
            blocks.append(
                f"[{label}]\n"
                f"ACTION: {action.get('raw_action', '')}\n"
                f"THOUGHT: {action.get('thought', '')}\n"
                f"OBSERVATION: {LLMHintRenderer._truncate(action.get('observation', ''))}"
            )
        return "\n\n".join(blocks)

    @staticmethod
    def _serialize_metadata(event: dict[str, Any], metadata_fields: Any) -> str:
        if metadata_fields:
            subset = {key: event[key] for key in metadata_fields if key in event}
        else:
            subset = dict(event)
        if "observation" in subset:
            # Bound the top-level observation; nested values (e.g. duplicate's current) are left as-is.
            subset["observation"] = LLMHintRenderer._truncate(subset["observation"])
        return json.dumps(subset, ensure_ascii=False, default=str)

    @staticmethod
    def _truncate(text: Any, limit: int = _TRAJECTORY_FIELD_LIMIT) -> str:
        text = str(text or "")
        return text if len(text) <= limit else text[:limit] + "...<truncated>"
