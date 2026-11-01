# src/toolpulse/state/features.py
"""Feature store: raw feature rows plus the derived numpy matrix (design D6).

numpy lives only in the state layer; `RawFeaturesRow` hashes stay stdlib tuples
in core. `trim` removes the oldest rows in lockstep with the grammar window but
leaves `matrix` untouched — the caller re-sets it from the surviving rows.
"""
from __future__ import annotations

import dataclasses

import numpy as np

from toolpulse.core.types import RawFeaturesRow


class FeatureStore:
    """Append-only rows + replaceable matrix; trim/restore for bounded memory."""

    def __init__(self) -> None:
        self.rows: list[RawFeaturesRow] = []
        self.matrix: list[np.ndarray] = []

    def append_row(self, row: RawFeaturesRow) -> None:
        self.rows.append(row)

    def set_matrix(self, matrix: list[np.ndarray]) -> None:
        self.matrix = list(matrix)

    def window(self, i: int, n: int) -> np.ndarray:
        return np.vstack(self.matrix[i:i + n])

    def __len__(self) -> int:
        return len(self.rows)

    def trim(self, n: int) -> None:
        """Drop the oldest n rows (keeps the newest); matrix is re-set by the caller."""
        if n <= 0:
            return
        del self.rows[:n]

    def snapshot(self) -> list[dict]:
        """Serialize rows; tuple hash fields become JSON-safe lists via asdict."""
        return [dataclasses.asdict(row) for row in self.rows]

    def restore(self, data: list[dict]) -> None:
        """Rebuild rows from snapshot dicts, converting list fields back to tuple."""
        self.rows = [
            RawFeaturesRow(
                thought_length=row["thought_length"],
                tool_hash=tuple(row["tool_hash"]),
                args_hash=tuple(row["args_hash"]),
                observation_length=row["observation_length"],
                execution_time=row["execution_time"],
                has_error=row["has_error"],
            )
            for row in data
        ]
        self.matrix = []
