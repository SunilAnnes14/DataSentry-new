"""Federated training orchestration.

The engine is pure ML: persistence and blockchain recording are attached
through the ``emit`` callback so that the engine can be tested in isolation.

Event sequence per round (emit(event, payload)):
    round_started    {round, global_hash}
    client_progress  {round, client, epoch, epochs}
    update_submitted {round, client, update_hash, num_samples, ...}
    round_analyzed   {round, analyses:[...]}
    round_completed  {round, metrics, included, excluded, global_hash, ...}
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

import numpy as np
import torch
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from torch import nn

from core.aggregation import AggregationInput, fedavg
from core.attack_simulator import AttackConfig
from core.client_manager import FederatedClient, LocalTrainingConfig
from core.security_engine import SecurityConfig, SecurityEngine
from core.trust_engine import TrustEngine
from datasets.prepare_data import FederatedDataset
from models.neural_network import create_model, flatten, get_params, hash_params, set_params, unflatten

Emit = Callable[[str, dict], None]

# Positive class for precision/recall/F1: malignant (sklearn target 0).
POSITIVE_LABEL = 0


@dataclass
class ExperimentConfig:
    mode: str = "custom"                 # clean | poisoned | protected | custom
    rounds: int = 3
    local_epochs: int = 2
    batch_size: int = 16
    learning_rate: float = 1e-3
    seed: int = 42
    partition: str = "dirichlet"
    dirichlet_alpha: float = 2.0
    defense_enabled: bool = True
    trust_alpha: float = 0.5
    attack: AttackConfig = field(default_factory=AttackConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)

    def validate(self) -> None:
        if not 1 <= self.rounds <= 50:
            raise ValueError("rounds must be within [1, 50]")
        if not 1 <= self.local_epochs <= 20:
            raise ValueError("local_epochs must be within [1, 20]")
        self.attack.validate()
        self.security.validate()

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def evaluate(vector: np.ndarray, template, X: np.ndarray, y: np.ndarray) -> dict[str, float]:
    model = create_model(0)
    set_params(model, unflatten(vector, template))
    model.eval()
    with torch.no_grad():
        logits = model(torch.tensor(X, dtype=torch.float32))
        loss = float(nn.functional.cross_entropy(logits, torch.tensor(y, dtype=torch.long)).item())
        pred = logits.argmax(1).numpy()
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "precision": float(precision_score(y, pred, pos_label=POSITIVE_LABEL, zero_division=0)),
        "recall": float(recall_score(y, pred, pos_label=POSITIVE_LABEL, zero_division=0)),
        "f1": float(f1_score(y, pred, pos_label=POSITIVE_LABEL, zero_division=0)),
        "loss": loss,
    }


class StopRequested(Exception):
    pass


def _noop(_e: str, _p: dict) -> None:
    pass


def run_federated(
    cfg: ExperimentConfig,
    data: FederatedDataset,
    emit: Emit = _noop,
    should_stop: Optional[Callable[[], bool]] = None,
) -> dict[str, Any]:
    cfg.validate()
    stop = should_stop or (lambda: False)
    clients = [FederatedClient(p, i) for i, p in enumerate(data.clients)]
    template = get_params(create_model(cfg.seed))
    global_vec = flatten(template)
    security = SecurityEngine(cfg.security, seed=cfg.seed)
    trust = TrustEngine(alpha=cfg.trust_alpha)
    local_cfg = LocalTrainingConfig(cfg.local_epochs, cfg.batch_size, cfg.learning_rate)

    initial = evaluate(global_vec, template, data.X_test, data.y_test)
    rounds_out: list[dict] = []
    started = time.time()

    for r in range(1, cfg.rounds + 1):
        if stop():
            raise StopRequested()
        global_hash = hash_params(unflatten(global_vec, template))
        emit("round_started", {"round": r, "global_hash": global_hash, "global_vector": global_vec})

        updates = []
        for c in clients:
            seed = cfg.seed * 1000 + r * 10 + c.index
            upd = c.local_train(
                global_vec, template, local_cfg, seed, cfg.attack,
                progress=lambda name, e, t, _r=r: emit("client_progress", {"round": _r, "client": name, "epoch": e, "epochs": t}),
                should_stop=stop,
            )
            upd_hash = hash_params(unflatten(upd.delta, template))
            updates.append((upd, upd_hash))
            emit("update_submitted", {
                "round": r, "client": upd.client, "update_hash": upd_hash, "num_samples": upd.num_samples,
                "epoch_losses": upd.epoch_losses, "local_accuracy": upd.local_accuracy,
                "is_malicious": upd.is_malicious, "attack_details": upd.attack_details, "delta": upd.delta,
            })

        analyses = security.analyze(
            [u.client for u, _ in updates], [u.delta for u, _ in updates], global_vec, template,
            data.X_val, data.y_val, enforce=cfg.defense_enabled,
            local_steps=[cfg.local_epochs * math.ceil(u.num_samples / cfg.batch_size) for u, _ in updates],
        )
        for a in analyses:
            trust.update(a.client, a.risk_score, a.decision)
        emit("round_analyzed", {"round": r, "analyses": [a.to_dict() for a in analyses], "trust": trust.snapshot()})

        agg_inputs = []
        for (u, _), a in zip(updates, analyses):
            admission = a.decision if cfg.defense_enabled else "ACCEPT"
            agg_inputs.append(AggregationInput(u.client, u.delta, u.num_samples, a.aggregation_weight, admission))
        agg = fedavg(global_vec, agg_inputs)
        global_vec = agg.new_global
        metrics = evaluate(global_vec, template, data.X_test, data.y_test)
        new_hash = hash_params(unflatten(global_vec, template))

        round_info = {
            "round": r,
            "metrics": metrics,
            "included": agg.included,
            "excluded": agg.excluded,
            "effective_weights": agg.effective_weights,
            "global_hash_before": global_hash,
            "global_hash": new_hash,
            "train_loss": float(np.mean([u.epoch_losses[-1] for u, _ in updates])),
            "analyses": [a.to_dict() for a in analyses],
            "updates": [{
                "client": u.client, "update_hash": h, "num_samples": u.num_samples,
                "is_malicious": u.is_malicious, "local_accuracy": u.local_accuracy,
                "epoch_losses": u.epoch_losses, "attack_details": u.attack_details,
            } for u, h in updates],
        }
        rounds_out.append(round_info)
        emit("round_completed", {**round_info, "global_vector": global_vec})

    final = rounds_out[-1]["metrics"] if rounds_out else initial
    return {
        "mode": cfg.mode,
        "config": cfg.to_dict(),
        "initial_metrics": initial,
        "final_metrics": final,
        "rounds": rounds_out,
        "trust": trust.snapshot(),
        "detection": _detection_summary(rounds_out),
        "final_global_hash": hash_params(unflatten(global_vec, template)),
        "duration_seconds": round(time.time() - started, 3),
        "final_global_vector": global_vec,
    }


def _detection_summary(rounds: list[dict]) -> dict:
    """Confusion counts of the security verdicts vs. ground truth (evaluation only)."""
    tp = fp = tn = fn = 0
    for rd in rounds:
        truth = {u["client"]: u["is_malicious"] for u in rd["updates"]}
        for a in rd["analyses"]:
            flagged = a["decision"] != "ACCEPT"
            mal = truth[a["client"]]
            tp += flagged and mal
            fp += flagged and not mal
            tn += (not flagged) and (not mal)
            fn += (not flagged) and mal
    return {"true_positives": tp, "false_positives": fp, "true_negatives": tn, "false_negatives": fn}


def run_centralized(cfg: ExperimentConfig, data: FederatedDataset, emit: Emit = _noop,
                    should_stop: Optional[Callable[[], bool]] = None) -> dict[str, Any]:
    """Centralised baseline: same network trained on the pooled client data
    for the same total number of epochs (rounds * local_epochs)."""
    stop = should_stop or (lambda: False)
    torch.manual_seed(cfg.seed)
    model = create_model(cfg.seed)
    template = get_params(model)
    X = torch.tensor(data.X_train_all, dtype=torch.float32)
    y = torch.tensor(data.y_train_all, dtype=torch.long)
    opt = torch.optim.Adam(model.parameters(), lr=cfg.learning_rate)
    loss_fn = nn.CrossEntropyLoss()
    gen = torch.Generator().manual_seed(cfg.seed)
    initial = evaluate(flatten(template), template, data.X_test, data.y_test)
    rounds_out = []
    started = time.time()
    for r in range(1, cfg.rounds + 1):
        losses = []
        for _ in range(cfg.local_epochs):
            if stop():
                raise StopRequested()
            perm = torch.randperm(len(y), generator=gen)
            tot = 0.0
            for s in range(0, len(perm), cfg.batch_size):
                b = perm[s:s + cfg.batch_size]
                opt.zero_grad()
                loss = loss_fn(model(X[b]), y[b])
                loss.backward()
                opt.step()
                tot += float(loss.item()) * len(b)
            losses.append(tot / len(y))
        vec = flatten(get_params(model))
        metrics = evaluate(vec, template, data.X_test, data.y_test)
        info = {"round": r, "metrics": metrics, "train_loss": losses[-1],
                "global_hash": hash_params(unflatten(vec, template))}
        rounds_out.append(info)
        emit("centralized_round", info)
    return {
        "mode": "centralized",
        "config": cfg.to_dict(),
        "initial_metrics": initial,
        "final_metrics": rounds_out[-1]["metrics"],
        "rounds": rounds_out,
        "final_global_hash": rounds_out[-1]["global_hash"],
        "duration_seconds": round(time.time() - started, 3),
    }
