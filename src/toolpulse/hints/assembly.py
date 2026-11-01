"""Assemble rendered hints with tool output for the host's next model input."""
from __future__ import annotations

import json
from collections.abc import Sequence

from toolpulse.core.types import Hint


def assemble_observation(observation: str, hints: Sequence[Hint], *,
                         hint_set_name: str = "remind_only") -> str:
    """Join hint texts in order, using JSON only for different_message_type.

    Plain output is unchanged when there are no hints. JSON output always
    retains both fields, with an empty hint string when there are no hints.
    This function formats content; the host still delivers it to the model.
    """
    hint_text = "\n".join(hint.text for hint in hints)
    if hint_set_name == "different_message_type":
        return json.dumps({"observation": observation, "hint": hint_text}, ensure_ascii=False)
    if not hints:
        return observation
    block = f"<tool_pulse>\n{hint_text}\n</tool_pulse>"
    return f"{observation}\n{block}" if observation else block
