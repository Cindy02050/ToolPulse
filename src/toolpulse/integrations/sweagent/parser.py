"""Adapt native function calls without reparsing shell-quoted editor arguments."""
from __future__ import annotations

import json
from dataclasses import replace

from toolpulse.core.protocols import ActionParser
from toolpulse.core.types import Action, StepObservation
from toolpulse.parsing.sweagent import SweAgentParser


class SWEAgentActionParser:
    def __init__(self, fallback: ActionParser | None = None) -> None:
        self.fallback = fallback if fallback is not None else SweAgentParser()

    def parse(self, step: StepObservation) -> Action:
        calls = (step.host_context or {}).get("tool_calls")
        if not calls:
            return self.fallback.parse(step)
        if len(calls) != 1:
            raise ValueError("SWE-agent integration expects exactly one tool call")
        function = calls[0]["function"]
        args = function["arguments"]
        if isinstance(args, str):
            args = json.loads(args)
        if not isinstance(args, dict):
            raise ValueError("Tool-call arguments must be a JSON object")
        name = function["name"]
        if name == "bash":
            command = args.get("command")
            if not isinstance(command, str):
                raise ValueError("bash tool-call command must be a string")
            action = self.fallback.parse(replace(step, raw_action=command, host_context=None))
            return Action(action.tool, action.args, step.raw_action)
        return Action(name, args, step.raw_action)
