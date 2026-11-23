"""Pydantic request/response models."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

import config
from core.attack_simulator import ATTACK_TYPES

ClientName = Literal[tuple(config.CLIENT_NAMES)]  # type: ignore[valid-type]
AttackType = Literal[ATTACK_TYPES]  # type: ignore[valid-type]


class AttackSettings(BaseModel):
    enabled: bool = True
    target_client: ClientName = "Hospital Delta"
    attack_type: AttackType = "label_flip_scaled"
    flip_rate: float = Field(1.0, ge=0.0, le=1.0)
    strength: float = Field(3.0, gt=0.0, le=100.0)


class SecuritySettings(BaseModel):
    accept_threshold: float = Field(0.40, gt=0.0, lt=1.0)
    reject_threshold: float = Field(0.70, gt=0.0, le=1.0)
    suspicious_policy: Literal["downweight", "exclude", "include"] = "downweight"
    suspicious_weight: float = Field(0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self):
        if self.accept_threshold >= self.reject_threshold:
            raise ValueError("accept_threshold must be lower than reject_threshold")
        return self


class Settings(BaseModel):
    rounds: int = Field(3, ge=1, le=20)
    local_epochs: int = Field(2, ge=1, le=10)
    batch_size: int = Field(16, ge=4, le=256)
    learning_rate: float = Field(0.001, gt=0.0, le=1.0)
    seed: int = Field(42, ge=0, le=2**31 - 1)
    partition: Literal["iid", "dirichlet"] = "dirichlet"
    dirichlet_alpha: float = Field(2.0, gt=0.0, le=100.0)
    defense_enabled: bool = True
    trust_alpha: float = Field(0.5, gt=0.0, le=1.0)
    blockchain_enabled: bool = True
    attack: AttackSettings = AttackSettings()
    security: SecuritySettings = SecuritySettings()


class StartTrainingRequest(BaseModel):
    mode: Literal["clean", "poisoned", "protected", "centralized", "custom", "suite"] = "custom"
    settings: Optional[dict[str, Any]] = Field(
        None, description="Optional one-off overrides merged over the saved settings")


class RegisterClientRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=64)
    organization_type: str = Field("hospital", max_length=32)


class SubmitUpdateRequest(BaseModel):
    client_name: ClientName
    update: list[float] = Field(..., description="Flat update delta in DSv1 parameter order")
    num_samples: int = Field(..., ge=1, le=1_000_000)
    experiment_id: Optional[str] = Field(None, description="Experiment whose round is used as reference (default: latest)")
    round_number: Optional[int] = Field(None, ge=1, description="Reference round (default: last round)")


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: bool
    training_state: str
    blockchain: dict[str, Any]


class ClientState(BaseModel):
    status: str = "idle"
    epoch: int = 0
    epochs: int = 0
    progress: float = 0.0
    risk: Optional[float] = None
    decision: Optional[str] = None
    included: Optional[bool] = None
    trust: Optional[float] = None
    update_hash: Optional[str] = None


class TrainingStatus(BaseModel):
    job_id: Optional[str]
    state: Literal["idle", "running", "stopping", "completed", "stopped", "failed"]
    mode: Optional[str]
    queue: list[str]
    experiment_id: Optional[str]
    current_round: int
    total_rounds: int
    phase: Optional[str]
    clients: dict[str, ClientState]
    logs: list[dict[str, Any]]
    warnings: list[str]
    error: Optional[str]
    started_at: Optional[str]
    finished_at: Optional[str]
    completed_experiments: list[dict[str, Any]]


class AnalysisResult(BaseModel):
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
    detector_mode: str
    risk_score: float = Field(..., ge=0.0, le=1.0)
    decision: Literal["ACCEPT", "SUSPICIOUS", "REJECT"]
    aggregation_weight: float
    explanation: list[str]


class SubmitUpdateResponse(BaseModel):
    update_id: int
    update_hash: str
    reference_experiment: str
    reference_round: int
    analysis: AnalysisResult
    note: str
