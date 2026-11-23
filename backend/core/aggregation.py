"""Federated Averaging over *admitted* client updates only.

Each update is a flat delta vector (local - global). FedAvg computes a
sample-count weighted mean of the admitted deltas and applies it to the
global model. Rejected updates are filtered out *before* any arithmetic so
they can never contribute to the global model.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class AggregationInput:
    client: str
    delta: np.ndarray
    num_samples: int
    weight_multiplier: float  # 1.0 = full weight, 0 < w < 1 = down-weighted, 0 = excluded
    decision: str  # ACCEPT / SUSPICIOUS / REJECT (or ACCEPT when defense disabled)


@dataclass
class AggregationResult:
    new_global: np.ndarray
    aggregated_delta: np.ndarray
    included: list[str]
    excluded: list[str]
    effective_weights: dict[str, float]


def fedavg(global_vector: np.ndarray, updates: list[AggregationInput]) -> AggregationResult:
    global_vector = np.asarray(global_vector, dtype=np.float32)
    admitted = [
        u for u in updates
        if u.decision != "REJECT" and u.weight_multiplier > 0 and u.num_samples > 0
    ]
    admitted_ids = {id(u) for u in admitted}
    excluded = [u.client for u in updates if id(u) not in admitted_ids]
    if not admitted:
        # Nothing trustworthy to aggregate: keep the previous global model.
        return AggregationResult(global_vector.copy(), np.zeros_like(global_vector), [], excluded, {})

    raw_w = np.array([u.num_samples * u.weight_multiplier for u in admitted], dtype=np.float64)
    norm_w = raw_w / raw_w.sum()
    stacked = np.stack([np.asarray(u.delta, dtype=np.float64) for u in admitted])
    agg = (norm_w[:, None] * stacked).sum(axis=0).astype(np.float32)
    return AggregationResult(
        new_global=(global_vector + agg).astype(np.float32),
        aggregated_delta=agg,
        included=[u.client for u in admitted],
        excluded=excluded,
        effective_weights={u.client: float(w) for u, w in zip(admitted, norm_w)},
    )
