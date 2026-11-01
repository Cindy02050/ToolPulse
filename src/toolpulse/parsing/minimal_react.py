"""Action protocol for the small framework in examples/minimal_react."""
from __future__ import annotations

import json

from toolpulse.core.types import Action, StepObservation


class MinimalReactParser:
    """Parse one JSON action: file(read/write) or check. No shell syntax."""

    def parse(self, step: StepObservation) -> Action:
        raw = step.raw_action
        if not raw.strip():
            return Action(None, {}, "")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Action must be a JSON object")
        tool, args = payload.get("tool"), payload.get("args")
        if tool not in ("file", "check") or not isinstance(args, dict):
            raise ValueError("Expected tool=file/check and an args object")
        if not isinstance(args.get("path"), str) or not args["path"].strip():
            raise ValueError("args.path must be a nonempty string")
        if tool == "file":
            if args.get("mode") not in ("read", "write"):
                raise ValueError("file mode must be read or write")
            if args["mode"] == "write" and not isinstance(args.get("content"), str):
                raise ValueError("file write requires string content")
        elif not isinstance(args.get("expected"), str):
            raise ValueError("check requires a string expected value")
        return Action(tool, args, raw)
