"""AI security engine: screens every model update before aggregation.

Per-update features (all computed relative to the other updates of the same
round, which makes them robust to non-IID data and to the shrinking update
magnitude as training converges):

  1. L2 update norm            -> robust z-score vs. round median (MAD)
  2. Cosine similarity         -> vs. coordinate-wise median of the OTHER updates
  3. Weight deviation          -> Euclidean distance to that leave-one-out median
  4. Validation loss impact    -> loss of (global + update) on the coordinator's
                                  validation set vs. the median candidate loss
  5. Update anomaly score      -> Isolation Forest over the normalised features
                                  (only once enough history exists)

Risk = 0.35*norm + 0.30*cosine_disagreement + 0.20*deviation + 0.15*val_impact

Decisions: risk < accept_threshold -> ACCEPT, risk >= reject_threshold -> REJECT,
otherwise SUSPICIOUS. The Isolation Forest can only *escalate* ACCEPT to
SUSPICIOUS when it corroborates a non-trivial rule-based risk; it can never
reject an update on its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import torch
from torch import nn

from models.anomaly_detector import InsufficientHistoryError, UpdateAnomalyDetector
from models.neural_network import create_model, set_params, unflatten

EPS = 1e-12
WEIGHTS = {"norm": 0.35, "cosine": 0.30, "deviation": 0.20, "validation": 0.15}


@dataclass
class SecurityConfig:
    accept_threshold: float = 0.40
    reject_threshold: float = 0.70
    suspicious_policy: str = "downweight"   # downweight | exclude | include
    suspicious_weight: float = 0.5
    mad_relative_floor: float = 0.15        # MAD scale floor as fraction of median (non-IID tolerance)
    z_soft: float = 1.5                     # robust z below this -> 0 anomaly
    z_hard: float = 5.0                     # robust z at/above this -> 1 anomaly
    if_min_history: int = 6
    if_escalation_threshold: float = 0.80
    if_corroboration_risk: float = 0.25

    def validate(self) -> None:
        if not 0.0 < self.accept_threshold < self.reject_threshold <= 1.0:
            raise ValueError("require 0 < accept_threshold < reject_threshold <= 1")
        if self.suspicious_policy not in ("downweight", "exclude", "include"):
            raise ValueError("suspicious_policy must be downweight, exclude or include")
        if not 0.0 <= self.suspicious_weight <= 1.0:
            raise ValueError("suspicious_weight must be in [0, 1]")

    def aggregation_weight(self, decision: str) -> float:
        if decision == "ACCEPT":
            return 1.0
        if decision == "REJECT":
            return 0.0
        return {"downweight": self.suspicious_weight, "exclude": 0.0, "include": 1.0}[self.suspicious_policy]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UpdateAnalysis:
    client: str
    l2_norm: float
    norm_per_step: float
    local_steps: int
    norm_z: float
    cosine_similarity: float
    weight_deviation: float
    validation_loss: float
    validation_loss_baseline: float
    norm_anomaly: float
    cosine_disagreement: float
    deviation_score: float
    validation_impact: float
    isolation_score: Optional[float]
    detector_mode: str                      # "hybrid" or "rule-based (warm-up)"
    risk_score: float
    decision: str
    aggregation_weight: float
    explanation: list[str] = field(default_factory=list)

    def feature_vector(self) -> list[float]:
        return [self.norm_anomaly, self.cosine_disagreement, self.deviation_score, self.validation_impact]

    def to_dict(self) -> dict:
        return asdict(self)


def _robust_z(values: np.ndarray, rel_floor: float) -> tuple[np.ndarray, float]:
    """Robust z-scores using the Median Absolute Deviation.

    The scale is floored at ``rel_floor * median`` so that a round in which
    honest clients happen to agree very closely does not turn small natural
    (non-IID) differences into large z-scores, and never reaches zero.
    """
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med)))
    scale = max(1.4826 * mad, rel_floor * abs(med), EPS)
    return (values - med) / scale, med


def _ramp(z: np.ndarray | float, lo: float, hi: float):
    return np.clip((np.asarray(z) - lo) / max(hi - lo, EPS), 0.0, 1.0)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < EPS or nb < EPS:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _val_loss(vector: np.ndarray, template, X_val: np.ndarray, y_val: np.ndarray) -> float:
    model = create_model(0)
    set_params(model, unflatten(vector, template))
    model.eval()
    with torch.no_grad():
        logits = model(torch.tensor(X_val, dtype=torch.float32))
        return float(nn.functional.cross_entropy(logits, torch.tensor(y_val, dtype=torch.long)).item())


class SecurityEngine:
    def __init__(self, config: SecurityConfig, seed: int = 42):
        config.validate()
        self.config = config
        self.seed = seed
        self.history: list[list[float]] = []   # feature vectors of previously ACCEPTED updates

    def analyze(
        self,
        clients: list[str],
        deltas: list[np.ndarray],
        global_vector: np.ndarray,
        template,
        X_val: np.ndarray,
        y_val: np.ndarray,
        enforce: bool = True,
        record_history: bool = True,
        local_steps: Optional[list[int]] = None,
    ) -> list[UpdateAnalysis]:
        cfg = self.config
        n = len(deltas)
        if n == 0:
            return []
        D = np.stack([np.asarray(d, dtype=np.float64) for d in deltas])
        norms = np.linalg.norm(D, axis=1)
        # Quantity skew: a client with more samples takes more optimizer steps and
        # naturally moves further. Magnitude statistics therefore use the
        # per-step displacement (steps derive from the declared sample count).
        steps = np.asarray(local_steps if local_steps else [1] * n, dtype=np.float64)
        steps = np.maximum(steps, 1.0)
        step_norms = norms / steps

        # 1. norm anomaly (upward deviations matter most; tiny updates are half-weighted)
        if n >= 3:
            z, _ = _robust_z(step_norms, cfg.mad_relative_floor)
        else:
            z = np.zeros(n)
        z_eff = np.maximum(z, 0) + 0.5 * np.maximum(-z, 0)
        norm_anom = _ramp(z_eff, cfg.z_soft, cfg.z_hard)

        # 2 + 3. cosine & deviation vs. leave-one-out coordinate-wise median
        cos = np.zeros(n)
        dev = np.zeros(n)
        for i in range(n):
            others = np.delete(D, i, axis=0)
            if len(others) == 0:
                continue
            ref = np.median(others / np.delete(steps, i)[:, None], axis=0)
            cos[i] = _cosine(D[i], ref)
            dev[i] = float(np.linalg.norm(D[i] / steps[i] - ref))
        # cosine disagreement: aligned (cos>=0.5) -> 0, orthogonal -> 0.5, opposed (cos<=-0.5) -> 1
        cos_dis = np.clip((0.5 - cos) / 1.0, 0.0, 1.0) if n >= 2 else np.zeros(n)
        if n >= 3:
            dz, _ = _robust_z(dev, cfg.mad_relative_floor)
            dev_score = _ramp(np.maximum(dz, 0), cfg.z_soft, cfg.z_hard)
        else:
            dev_score = np.zeros(n)

        # 4. validation loss impact
        g = np.asarray(global_vector, dtype=np.float64)
        losses = np.array([_val_loss((g + D[i]).astype(np.float32), template, X_val, y_val) for i in range(n)])
        base = float(np.median(losses))
        rel_increase = np.maximum(losses - base, 0.0) / max(base, EPS)
        val_impact = 1.0 - np.exp(-rel_increase / 0.5)   # +50 % loss -> 0.63, +150 % -> 0.95

        risk = (WEIGHTS["norm"] * norm_anom + WEIGHTS["cosine"] * cos_dis
                + WEIGHTS["deviation"] * dev_score + WEIGHTS["validation"] * val_impact)
        risk = np.clip(risk, 0.0, 1.0)

        # 5. Isolation Forest (hybrid mode once enough history exists)
        feats = np.stack([norm_anom, cos_dis, dev_score, val_impact], axis=1)
        iso: Optional[np.ndarray] = None
        mode = "rule-based (warm-up)"
        train = np.array(self.history + feats.tolist()) if self.history else feats
        if len(self.history) + n >= cfg.if_min_history:
            try:
                iso = UpdateAnomalyDetector(cfg.if_min_history, seed=self.seed).fit(train).score(feats)
                mode = "hybrid"
            except InsufficientHistoryError:
                iso = None

        results: list[UpdateAnalysis] = []
        for i, client in enumerate(clients):
            r = float(risk[i])
            if r >= cfg.reject_threshold:
                decision = "REJECT"
            elif r >= cfg.accept_threshold:
                decision = "SUSPICIOUS"
            else:
                decision = "ACCEPT"
            explanation = self._explain(i, step_norms, z, cos, losses, base, norm_anom, cos_dis, dev_score, val_impact)
            if (iso is not None and decision == "ACCEPT" and iso[i] >= cfg.if_escalation_threshold
                    and r >= cfg.if_corroboration_risk):
                decision = "SUSPICIOUS"
                explanation.append(
                    f"Isolation Forest anomaly {iso[i]:.2f} corroborates elevated risk {r:.2f}: escalated to SUSPICIOUS."
                )
            if decision == "ACCEPT" and not explanation:
                explanation.append("Update is consistent with peer consensus on all monitored signals.")
            explanation.insert(0, self._decision_reason(decision, r))
            weight = cfg.aggregation_weight(decision) if enforce else 1.0
            if not enforce and decision != "ACCEPT":
                explanation.append("Defense disabled: update was aggregated anyway (audit only).")
            results.append(UpdateAnalysis(
                client=client,
                l2_norm=float(norms[i]),
                norm_per_step=float(step_norms[i]),
                local_steps=int(steps[i]),
                norm_z=float(z[i]),
                cosine_similarity=float(cos[i]),
                weight_deviation=float(dev[i]),
                validation_loss=float(losses[i]),
                validation_loss_baseline=base,
                norm_anomaly=float(norm_anom[i]),
                cosine_disagreement=float(cos_dis[i]),
                deviation_score=float(dev_score[i]),
                validation_impact=float(val_impact[i]),
                isolation_score=None if iso is None else float(iso[i]),
                detector_mode=mode,
                risk_score=round(r, 4),
                decision=decision,
                aggregation_weight=weight,
                explanation=explanation,
            ))
        if record_history:
            self.history.extend(a.feature_vector() for a in results if a.decision == "ACCEPT")
        return results

    def _decision_reason(self, decision: str, risk: float) -> str:
        c = self.config
        if decision == "REJECT":
            return f"Risk {risk:.3f} >= reject threshold {c.reject_threshold:.2f}: update excluded from aggregation."
        if decision == "SUSPICIOUS":
            policy = {"downweight": f"down-weighted to {c.suspicious_weight:.0%}",
                      "exclude": "excluded", "include": "included at full weight"}[c.suspicious_policy]
            return f"Risk {risk:.3f} in suspicious band [{c.accept_threshold:.2f}, {c.reject_threshold:.2f}): {policy}."
        return f"Risk {risk:.3f} < accept threshold {c.accept_threshold:.2f}: accepted."

    @staticmethod
    def _explain(i, norms, z, cos, losses, base, na, cd, dv, vi) -> list[str]:
        out = []
        med = float(np.median(norms))
        if na[i] > 0.3:
            out.append(f"Per-step update norm is {norms[i] / max(med, EPS):.1f}x the round median (robust z={z[i]:.1f}).")
        if cd[i] > 0.3:
            out.append(f"Update direction disagrees with peer consensus (cosine similarity {cos[i]:+.2f}).")
        if dv[i] > 0.3:
            out.append("Parameters deviate strongly from the coordinate-wise median of the other updates.")
        if vi[i] > 0.3:
            out.append(f"Applying this update raises validation loss to {losses[i]:.3f} vs. median candidate {base:.3f} "
                       f"(+{(losses[i] / max(base, EPS) - 1) * 100:.0f}%).")
        return out
