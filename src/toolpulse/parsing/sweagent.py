"""SWE-agent action syntax adapter.

``SweAgentParser.parse`` ports legacy ``parse_action``
(``sweagent/agent/tool_familiar.py:61-112`` plus ``_second_token`` at 25-26)
onto ``StepObservation``/``Action``:

- the legacy ``state`` parameter becomes ``step.host_context`` (the ``edit``
  branch reads ``open_file`` from it, json-string-or-mapping, verbatim);
- the bash fallback delegates timeout-wrapper stripping to
  ``toolpulse.parsing.shell.strip_timeout_wrapper`` (no local copy);
- ``raw_action`` is ALWAYS the FULL stripped original action
  (``step.raw_action.strip()``, legacy ``ToolFamiliar._action_from_step``
  convention — 2026-10-31 final review revision): the ``cd … && …`` last-segment truncation
  affects only tool/args extraction, so duplicate identity distinguishes the
  cd form from the bare command.  ``args`` keeps the truncated bash command
  where legacy did (the bash fallback strips the timeout wrapper off the
  truncated segment).
"""

from __future__ import annotations

import json

from toolpulse.core.types import Action, StepObservation
from toolpulse.parsing.shell import strip_timeout_wrapper


def _second_token(parts: list[str]) -> str | None:
    return parts[1] if len(parts) > 1 else None


class SweAgentParser:
    def parse(self, step: StepObservation) -> Action:
        raw_action = step.raw_action.strip()   # full stripped original — never truncated
        if not raw_action:
            return Action(None, {}, "")

        action_for_parsing = raw_action
        if action_for_parsing.startswith("cd ") and "&&" in action_for_parsing:
            action_for_parsing = action_for_parsing.split("&&")[-1].strip()
            if not action_for_parsing:
                return Action("cd", {}, raw_action)

        parts = action_for_parsing.split()
        first_word = parts[0] if parts else ""

        if action_for_parsing.startswith("str_replace_editor"):
            return Action("str_replace_editor", {
                "command": parts[1] if len(parts) >= 2 else "view",
                "path": parts[2] if len(parts) > 2 else None,
                "view_range": "--view_range" in action_for_parsing,
            }, raw_action)

        if first_word == "open":
            return Action("open", {"path": _second_token(parts)}, raw_action)

        if first_word == "goto":
            return Action("goto", {}, raw_action)

        if first_word in ("scroll_down", "scroll_up"):
            return Action(first_word, {}, raw_action)

        if first_word == "edit":
            target = None
            state = step.host_context
            if state:
                try:
                    state_dict = json.loads(state) if isinstance(state, str) else state
                    target = state_dict.get("open_file")
                except (json.JSONDecodeError, TypeError, AttributeError):
                    target = None
            return Action("edit", {"path": target}, raw_action)

        if first_word == "create":
            return Action("create", {"path": _second_token(parts)}, raw_action)

        if first_word == "search_file":
            return Action("search_file", {}, raw_action)

        if first_word in ("search_dir", "find_file"):
            return Action(first_word, {}, raw_action)

        command = strip_timeout_wrapper(action_for_parsing)
        command_parts = command.split()
        command_first_word = command_parts[0] if command_parts else action_for_parsing
        return Action(f"bash-{command_first_word}", command, raw_action)
