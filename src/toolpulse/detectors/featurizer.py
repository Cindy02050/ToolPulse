"""Step featurizer: encode steps into one shared, causally fitted 36-dim space.

Ported from legacy `sweagent/agent/algorithm/matrix_profile.py` (lines 20-165);
`RawStepFeatures` is replaced by core's `RawFeaturesRow` (tuple hashes, stdlib-pure
core), so `triple_hash_vector` returns a tuple — the single sanctioned deviation
from the legacy source, which returns a numpy array.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

import numpy as np

from toolpulse.core.types import RawFeaturesRow


def stable_hash_int(text: str, algorithm: str) -> int:
    encoded = text.encode("utf-8")
    if algorithm == "md5":
        return int(hashlib.md5(encoded).hexdigest(), 16)
    if algorithm == "blake2b":
        return int(hashlib.blake2b(encoded, digest_size=8).hexdigest(), 16)
    if algorithm == "sha256":
        return int(hashlib.sha256(encoded).hexdigest(), 16)
    message = f"Unknown hash algorithm: {algorithm}"
    raise ValueError(message)


def triple_hash_vector(text: str, dim: int = 16) -> tuple[float, ...]:
    """Map text to three distinct dimensions and L2-normalize the block."""
    vector = np.zeros(dim, dtype=float)
    used: set[int] = set()

    for algorithm in ("md5", "blake2b", "sha256"):
        index = stable_hash_int(text, algorithm) % dim
        while index in used:
            index = (index + 1) % dim
        used.add(index)
        vector[index] = 1.0

    vector = vector / (np.linalg.norm(vector) + 1e-8)
    # Deviation from legacy: return a stdlib tuple (RawFeaturesRow contract),
    # not the numpy array the legacy triple_hash_vector returns.
    return tuple(vector.tolist())


@dataclass(frozen=True)
class FeatureWeights:
    thought: float = 0.25
    tool: float = 0.80
    args: float = 0.45
    observation: float = 0.30
    execution: float = 0.35
    error: float = 0.70


class StepFeaturizer:
    """Encode actions in one shared, causally fitted 36-dimensional space."""

    n_dims = 36

    def __init__(
        self,
        weights: FeatureWeights | None = None,
        scalar_clip: float = 5.0,
        scalar_eps: float = 1e-8,
        scalar_warmup: int = 2,
    ) -> None:
        self.weights = weights or FeatureWeights()
        self.scalar_clip = scalar_clip
        self.scalar_eps = scalar_eps
        self.scalar_warmup = scalar_warmup

    def extract(self, thought: str, tool: str, args, observation: str, execution_time: float, *, has_error: bool) -> RawFeaturesRow:
        thought = str(thought or "")
        tool = str(tool or "UNKNOWN")
        observation = str(observation or "")
        execution_time = float(execution_time or 0.0)
        serialized_args = json.dumps(
            args,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return RawFeaturesRow(
            thought_length=float(len(thought)),
            tool_hash=triple_hash_vector(tool),
            args_hash=triple_hash_vector(serialized_args),
            observation_length=float(len(observation)),
            execution_time=execution_time,
            has_error=has_error,
        )

    def transform_history(self, rows: list[RawFeaturesRow]) -> list[np.ndarray]:
        """Fit scalar statistics on prior steps and re-encode the full history.

        The newest step is excluded from fitting so an outlier cannot weaken its
        own distance. Every step is then transformed with the same statistics.
        """
        if not rows:
            return []

        reference = rows[:-1]
        thought_z = self._standardize(
            [item.thought_length for item in rows],
            [item.thought_length for item in reference],
        )
        observation_z = self._standardize(
            [item.observation_length for item in rows],
            [item.observation_length for item in reference],
        )
        execution_z = self._standardize(
            [item.execution_time for item in rows],
            [item.execution_time for item in reference],
        )

        encoded = []
        for index, item in enumerate(rows):
            # RawFeaturesRow hashes are tuples; scale them as arrays (legacy rows
            # held numpy arrays, so the bare `weight * hash` carried over as-is
            # would raise TypeError on a tuple).
            vector = np.concatenate(
                [
                    np.array([self.weights.thought * thought_z[index]]),
                    self.weights.tool * np.asarray(item.tool_hash, dtype=float),
                    self.weights.args * np.asarray(item.args_hash, dtype=float),
                    np.array(
                        [
                            self.weights.observation * observation_z[index],
                            self.weights.execution * execution_z[index],
                            self.weights.error * float(item.has_error),
                        ]
                    ),
                ]
            ).astype(float)
            if vector.shape != (self.n_dims,):
                message = f"Expected {self.n_dims} features, got {vector.shape}"
                raise RuntimeError(message)
            encoded.append(vector)
        return encoded

    def _standardize(self, values: list[float], reference: list[float]) -> np.ndarray:
        logged_values = np.log1p(np.maximum(np.asarray(values, dtype=float), 0.0))
        if len(reference) < self.scalar_warmup:
            return np.zeros_like(logged_values)

        logged_reference = np.log1p(np.maximum(np.asarray(reference, dtype=float), 0.0))
        std = float(np.std(logged_reference, ddof=1))
        if not math.isfinite(std) or std < self.scalar_eps:
            return np.zeros_like(logged_values)

        mean = float(np.mean(logged_reference))
        standardized = (logged_values - mean) / math.sqrt(std * std + self.scalar_eps)
        return np.clip(standardized, -self.scalar_clip, self.scalar_clip)
