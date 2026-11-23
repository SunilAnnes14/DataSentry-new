"""Participant trust scoring.

    Trust = 100 * (1 - EMA(risk))

A participant with no history starts at the neutral score of 50 (EMA = 0.5).
Trust is a behavioural signal derived from past anomaly scores; it is NOT
proof of malicious intent (non-IID data or faulty hardware can also produce
unusual updates).
"""
from __future__ import annotations

from dataclasses import dataclass, field

NEUTRAL_TRUST = 50.0


@dataclass
class TrustRecord:
    ema_risk: float = 0.5
    observations: int = 0
    accepted: int = 0
    suspicious: int = 0
    rejected: int = 0
    history: list[float] = field(default_factory=list)

    @property
    def trust(self) -> float:
        if self.observations == 0:
            return NEUTRAL_TRUST
        return round(100.0 * (1.0 - self.ema_risk), 2)


class TrustEngine:
    def __init__(self, alpha: float = 0.5):
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self.alpha = alpha
        self.records: dict[str, TrustRecord] = {}

    def get(self, client: str) -> TrustRecord:
        return self.records.setdefault(client, TrustRecord())

    def trust(self, client: str) -> float:
        return self.get(client).trust

    def update(self, client: str, risk: float, decision: str) -> float:
        risk = min(max(float(risk), 0.0), 1.0)
        rec = self.get(client)
        rec.ema_risk = self.alpha * risk + (1.0 - self.alpha) * rec.ema_risk
        rec.observations += 1
        if decision == "ACCEPT":
            rec.accepted += 1
        elif decision == "SUSPICIOUS":
            rec.suspicious += 1
        elif decision == "REJECT":
            rec.rejected += 1
        rec.history.append(rec.trust)
        return rec.trust

    def snapshot(self) -> dict[str, dict]:
        return {
            c: {
                "trust": r.trust, "ema_risk": round(r.ema_risk, 4), "observations": r.observations,
                "accepted": r.accepted, "suspicious": r.suspicious, "rejected": r.rejected,
                "history": list(r.history),
            }
            for c, r in self.records.items()
        }
