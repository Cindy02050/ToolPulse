# src/toolpulse/llm/stub.py
"""Deterministic ``ChatClient`` for tests and offline runs."""
from __future__ import annotations


class StubChatClient:
    """Return canned responses in order and record every call.

    Once the canned responses are exhausted the last one repeats; with no
    responses configured every call returns the empty string.
    """

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses) if responses is not None else []
        self.calls: list[dict[str, str | None]] = []

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system})
        if not self.responses:
            return ""
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]
