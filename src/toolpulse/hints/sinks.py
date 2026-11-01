# src/toolpulse/hints/sinks.py
"""Hint delivery channels (D21: sinks deliver hints, they never inject them).

Each sink implements the ``HintSink`` protocol (core.protocols): ``emit(hints, step)``
routes already-rendered hints to a destination; none of them mutate the hint list.
"""
from __future__ import annotations

import logging
from typing import Callable

from toolpulse.core.types import Hint, StepObservation


class ListSink:
    """Keep recent hints; ``max_hints=None`` explicitly retains every hint."""

    def __init__(self, max_hints: int | None = 1000) -> None:
        if max_hints is not None and (type(max_hints) is not int or max_hints < 1):
            raise ValueError("max_hints must be a positive integer or None")
        self.max_hints = max_hints
        self.hints: list[Hint] = []

    def emit(self, hints: list[Hint], step: StepObservation) -> None:
        self.hints.extend(hints)
        if self.max_hints is not None:
            del self.hints[:-self.max_hints]

    def clear(self) -> None:
        self.hints.clear()


class CallbackSink:
    """Forward each batch to ``fn(hints, step)``; delivery channel only (D21)."""

    def __init__(self, fn: Callable[[list[Hint], StepObservation], None]) -> None:
        self.fn = fn

    def emit(self, hints: list[Hint], step: StepObservation) -> None:
        self.fn(hints, step)


class LoggingSink:
    """Log each hint text at INFO on ``logger`` (default "toolpulse"); D21 delivery only."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger if logger is not None else logging.getLogger("toolpulse")

    def emit(self, hints: list[Hint], step: StepObservation) -> None:
        for hint in hints:
            self.logger.info(hint.text)
