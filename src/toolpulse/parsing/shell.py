"""Generic shell command normalization shared by all ToolPulse layers.

``strip_timeout_wrapper`` merges the duplicate ``_strip_timeout_wrapper``
implementations from legacy ``sweagent/agent/tool_familiar.py:29-58`` and
``sweagent/agent/algorithm/utils/action_semantic.py:338-366`` (logic
identical; one canonical copy kept here).
"""

from __future__ import annotations

import shlex


def strip_timeout_wrapper(cmd: str) -> str:
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return cmd
    if not parts or parts[0] != "timeout":
        return cmd

    i = 1
    while i < len(parts):
        token = parts[i]
        if token == "--":
            i += 1
            break
        if token.startswith("--signal=") or token.startswith("--kill-after="):
            i += 1
            continue
        if token in ("-s", "--signal", "-k", "--kill-after"):
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue

        i += 1
        break

    if i >= len(parts):
        return cmd
    return " ".join(shlex.quote(part) for part in parts[i:])
