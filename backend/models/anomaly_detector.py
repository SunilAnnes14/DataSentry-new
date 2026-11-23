"""Isolation Forest wrapper for update-level anomaly scoring.

The detector works on *scale-free* per-update feature vectors (the normalised
norm/cosine/deviation/validation scores produced by the security engine), so
that its notion of "normal" does not drift as the global model converges and
update magnitudes shrink.

It refuses to fit on fewer than ``min_samples`` vectors; callers must use the
rule-based fallback in that case.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import IsolationForest


class InsufficientHistoryError(RuntimeError):
    pass


class UpdateAnomalyDetector:
    def __init__(self, min_samples: int = 6, n_estimators: int = 200, seed: int = 42):
        if min_samples < 2:
            raise ValueError("min_samples must be >= 2 (never fit on a single sample)")
        self.min_samples = min_samples
        self.n_estimators = n_estimators
        self.seed = seed
        self._model: IsolationForest | None = None
        self.fitted_on = 0

    @property
    def is_fitted(self) -> bool:
        return self._model is not None

    def fit(self, X: np.ndarray) -> "UpdateAnomalyDetector":
        X = np.asarray(X, dtype=np.float64)
        if X.ndim != 2 or len(X) < self.min_samples:
            raise InsufficientHistoryError(
                f"need >= {self.min_samples} feature vectors, got {0 if X.ndim != 2 else len(X)}"
            )
        self._model = IsolationForest(
            n_estimators=self.n_estimators,
            contamination="auto",
            max_samples=min(256, len(X)),
            random_state=self.seed,
        ).fit(X)
        self.fitted_on = len(X)
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        """Normalised anomaly score in [0, 1] (0 = typical, 1 = highly anomalous).

        sklearn's ``score_samples`` returns -s(x) where s(x) in (0, 1] is the
        original Isolation Forest anomaly score; s ~ 0.5 is unremarkable and
        s -> 1 is anomalous. We map s in [0.5, 0.75] linearly onto [0, 1].
        """
        if self._model is None:
            raise InsufficientHistoryError("detector not fitted")
        s = -self._model.score_samples(np.asarray(X, dtype=np.float64))
        return np.clip((s - 0.5) / 0.25, 0.0, 1.0)
