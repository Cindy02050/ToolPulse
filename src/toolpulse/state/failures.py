# src/toolpulse/state/failures.py
from __future__ import annotations

from dataclasses import dataclass

from toolpulse.core.types import FailureCluster, FailureSignature   # state→core allowed (D8/D9)

__all__ = ["FailureCluster", "FailureSignature", "FailureTable"]


@dataclass
class FailureTable:
    clusters: dict[FailureSignature, FailureCluster]

    def __init__(self) -> None:
        self.clusters = {}

    def expire(self, current_step: int, window: int) -> None:
        """Port of _expire_failure_clusters (multi_granularity.py:264-269)."""
        self.clusters = {
            sig: cluster for sig, cluster in self.clusters.items()
            if current_step - cluster.last_seen_step <= window
        }

    def prune_by_tool(self, tool: str) -> None:
        """Port of the Vp branch in _maybe_failed_action (multi_granularity.py:233-236)."""
        self.clusters = {sig: c for sig, c in self.clusters.items() if sig[0] != tool}

    def clear(self) -> None:
        self.clusters = {}

    def snapshot(self) -> list:
        # JSON-safe encoding (2026-10-31 final review revision): "|"-joining signatures corrupts
        # any signature whose tool/type/fingerprint itself contains "|".  Cluster
        # dicts are copied so the snapshot holds no live references.
        return [
            [list(sig), {"count": c.count, "last_seen_step": c.last_seen_step}]
            for sig, c in self.clusters.items()
        ]

    def restore(self, data: list) -> None:
        # Rebuild tuple keys (JSON round-trips them as lists); copy cluster dicts.
        self.clusters = {
            tuple(sig): FailureCluster(count=cluster["count"], last_seen_step=cluster["last_seen_step"])
            for sig, cluster in data
        }
