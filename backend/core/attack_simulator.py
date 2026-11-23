"""Malicious participant simulator.

Supported attack types
    label_flip         flip ``flip_rate`` of the attacker's training labels, train
                       normally, submit the resulting (honest-looking) update
    label_flip_scaled  label flipping + boost the poisoned update by ``strength``
                       (a "boosted"/model-replacement style attack)
    sign_flip          train honestly, then submit -strength * delta
    scaling            train honestly, then submit strength * delta

All randomness is driven by an explicit seed so experiments are reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

ATTACK_TYPES = ("label_flip", "label_flip_scaled", "sign_flip", "scaling")


@dataclass
class AttackConfig:
    enabled: bool = False
    target_client: str = "Hospital Delta"
    attack_type: str = "label_flip_scaled"
    flip_rate: float = 1.0      # fraction of labels flipped (label-flip types)
    strength: float = 3.0       # multiplier for update manipulation types

    def validate(self) -> None:
        if self.attack_type not in ATTACK_TYPES:
            raise ValueError(f"attack_type must be one of {ATTACK_TYPES}")
        if not 0.0 <= self.flip_rate <= 1.0:
            raise ValueError("flip_rate must be within [0, 1]")
        if not 0.0 < self.strength <= 100.0:
            raise ValueError("strength must be within (0, 100]")

    def applies_to(self, client: str) -> bool:
        return self.enabled and client == self.target_client

    @property
    def flips_labels(self) -> bool:
        return self.attack_type in ("label_flip", "label_flip_scaled")

    def to_dict(self) -> dict:
        return asdict(self)


def flip_labels(y: np.ndarray, flip_rate: float, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (poisoned_labels, flipped_indices) for binary labels."""
    y = np.asarray(y).copy()
    n_flip = int(round(flip_rate * len(y)))
    rng = np.random.default_rng(seed)
    idx = np.sort(rng.choice(len(y), size=n_flip, replace=False)) if n_flip else np.array([], dtype=int)
    y[idx] = 1 - y[idx]
    return y, idx


def manipulate_update(delta: np.ndarray, cfg: AttackConfig) -> np.ndarray:
    delta = np.asarray(delta, dtype=np.float32)
    if cfg.attack_type == "sign_flip":
        return (-cfg.strength * delta).astype(np.float32)
    if cfg.attack_type in ("scaling", "label_flip_scaled"):
        return (cfg.strength * delta).astype(np.float32)
    return delta.copy()
