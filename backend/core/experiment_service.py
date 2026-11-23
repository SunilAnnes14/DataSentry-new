"""Experiment orchestration: background jobs, persistence, artifacts, blockchain.

The training engine emits events; this service turns each event into
SQLite rows, artifact files (so hashes can be independently re-computed) and
on-chain transactions. Failed transactions are persisted with status
"failed" and surfaced as job warnings - never silently dropped.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import asdict
from typing import Any, Optional

import numpy as np

import config
from core import database as db
from core.attack_simulator import AttackConfig
from core.blockchain_service import BlockchainError, BlockchainService, blockchain
from core.security_engine import SecurityConfig
from core.training_engine import ExperimentConfig, StopRequested, run_centralized, run_federated
from datasets.prepare_data import load_federated_dataset

log = logging.getLogger("datasentry.experiments")

MODES = ("clean", "poisoned", "protected", "centralized", "custom")
SUITE = ("centralized", "clean", "poisoned", "protected")

DEFAULT_SETTINGS: dict[str, Any] = {
    "rounds": 3,
    "local_epochs": 2,
    "batch_size": 16,
    "learning_rate": 0.001,
    "seed": config.SEED,
    "partition": "dirichlet",
    "dirichlet_alpha": 2.0,
    "defense_enabled": True,
    "trust_alpha": 0.5,
    "blockchain_enabled": config.BLOCKCHAIN_ENABLED,
    "attack": AttackConfig(enabled=True).to_dict(),
    "security": {k: v for k, v in SecurityConfig().to_dict().items()
                 if k in ("accept_threshold", "reject_threshold", "suspicious_policy", "suspicious_weight")},
}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class SettingsStore:
    def __init__(self):
        self.path = config.DATA_DIR / "settings.json"
        self._lock = threading.Lock()

    def get(self) -> dict:
        with self._lock:
            if self.path.exists():
                try:
                    stored = json.loads(self.path.read_text())
                    merged = copy.deepcopy(DEFAULT_SETTINGS)
                    for k, v in stored.items():
                        if isinstance(v, dict) and isinstance(merged.get(k), dict):
                            merged[k].update(v)
                        else:
                            merged[k] = v
                    return merged
                except (json.JSONDecodeError, OSError):
                    log.warning("settings file unreadable, using defaults")
            return copy.deepcopy(DEFAULT_SETTINGS)

    def save(self, settings: dict) -> dict:
        build_config("custom", settings).validate()  # raises ValueError if invalid
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(settings, indent=2))
        return settings

    def reset(self) -> dict:
        with self._lock:
            if self.path.exists():
                self.path.unlink()
        return self.get()


def build_config(mode: str, s: dict) -> ExperimentConfig:
    attack = AttackConfig(**{**AttackConfig().to_dict(), **s.get("attack", {})})
    sec_defaults = SecurityConfig().to_dict()
    security = SecurityConfig(**{**sec_defaults, **{k: v for k, v in s.get("security", {}).items() if k in sec_defaults}})
    defense = bool(s.get("defense_enabled", True))
    if mode == "clean":
        attack.enabled, defense = False, False
    elif mode == "poisoned":
        attack.enabled, defense = True, False
    elif mode == "protected":
        attack.enabled, defense = True, True
    return ExperimentConfig(
        mode=mode, rounds=int(s["rounds"]), local_epochs=int(s["local_epochs"]), batch_size=int(s["batch_size"]),
        learning_rate=float(s["learning_rate"]), seed=int(s["seed"]), partition=s["partition"],
        dirichlet_alpha=float(s["dirichlet_alpha"]), defense_enabled=defense, trust_alpha=float(s["trust_alpha"]),
        attack=attack, security=security,
    )


class ExperimentService:
    def __init__(self, chain: BlockchainService = blockchain):
        self.chain = chain
        self.settings = SettingsStore()
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._status: dict[str, Any] = self._idle_status()

    # ---------------------------------------------------------------- status
    @staticmethod
    def _idle_status() -> dict:
        return {
            "job_id": None, "state": "idle", "mode": None, "queue": [], "experiment_id": None,
            "current_round": 0, "total_rounds": 0, "phase": None, "clients": {}, "logs": [],
            "warnings": [], "error": None, "started_at": None, "finished_at": None, "completed_experiments": [],
        }

    def status(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._status)

    def _set(self, **kw) -> None:
        with self._lock:
            self._status.update(kw)

    def _log(self, msg: str, level: str = "info") -> None:
        log.log(logging.WARNING if level == "warning" else logging.INFO, msg)
        with self._lock:
            self._status["logs"].append({"t": db.now(), "level": level, "msg": msg})
            self._status["logs"] = self._status["logs"][-120:]
            if level == "warning":
                self._status["warnings"].append(msg)

    def _client_state(self, name: str, **kw) -> None:
        with self._lock:
            self._status["clients"].setdefault(name, {}).update(kw)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------- clients
    def bootstrap_clients(self) -> None:
        """Ensure the four hospitals exist in SQLite and are registered on-chain."""
        data = load_federated_dataset(config.CLIENT_NAMES, seed=self.settings.get()["seed"])
        for i, part in enumerate(data.clients):
            row = db.query_one("SELECT * FROM clients WHERE name = ?", [part.name])
            fields = {"num_samples": part.num_samples, "label_counts": part.label_counts()}
            if row is None:
                db.insert("clients", {"name": part.name, "organization_type": "hospital", **fields})
            else:
                db.update("clients", {"name": part.name}, fields)
        if self.settings.get().get("blockchain_enabled", True):
            self.register_all_on_chain()

    def register_all_on_chain(self) -> list[dict]:
        out = []
        if not self.chain.ready and not self.chain.connect():
            return out
        for i, name in enumerate(config.CLIENT_NAMES):
            out.append(self.register_client_on_chain(i, name))
        return out

    def register_client_on_chain(self, index: int, name: str) -> dict:
        addr = self.chain.client_address(index)
        try:
            rc = self.chain.register_participant(index, name)
        except BlockchainError as e:
            self._record_tx(None, None, None, name, "register", None, error=e)
            raise
        if rc is not None:
            self._record_tx(None, None, None, name, "register", rc)
            tx = rc["transactionHash"]
        else:
            prev = db.query_one("SELECT registration_tx FROM clients WHERE name = ?", [name])
            tx = prev["registration_tx"] if prev else None
        db.update("clients", {"name": name}, {"wallet_address": addr, "registered_on_chain": 1,
                                               "registration_tx": tx})
        return {"name": name, "wallet_address": addr, "registration_tx": tx, "newly_registered": rc is not None}

    # -------------------------------------------------------------- control
    def start(self, mode: str, settings_override: Optional[dict] = None) -> dict:
        if mode != "suite" and mode not in MODES:
            raise ValueError(f"mode must be one of {MODES + ('suite',)}")
        with self._lock:
            if self.running:
                raise RuntimeError("an experiment is already running")
            settings = self.settings.get()
            if settings_override:
                for k, v in settings_override.items():
                    if isinstance(v, dict) and isinstance(settings.get(k), dict):
                        settings[k].update(v)
                    else:
                        settings[k] = v
            queue = list(SUITE) if mode == "suite" else [mode]
            for m in queue:
                build_config(m, settings).validate()
            self._stop.clear()
            job_id = uuid.uuid4().hex[:12]
            self._status = {**self._idle_status(), "job_id": job_id, "state": "running", "mode": mode,
                            "queue": queue, "started_at": db.now()}
            self._thread = threading.Thread(target=self._run_queue, args=(queue, settings), daemon=True,
                                            name=f"experiment-{job_id}")
            self._thread.start()
            return self.status()

    def stop(self) -> dict:
        if not self.running:
            raise RuntimeError("no experiment is running")
        self._stop.set()
        self._set(state="stopping")
        self._log("Stop requested; finishing current step...")
        return self.status()

    def reset(self) -> dict:
        if self.running:
            raise RuntimeError("cannot reset while an experiment is running")
        db.reset_experiments()
        import shutil
        if config.ARTIFACT_DIR.exists():
            shutil.rmtree(config.ARTIFACT_DIR, ignore_errors=True)
        config.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        for m in ("clean", "poisoned", "protected", "centralized", "custom"):
            p = config.EXPERIMENTS_DIR / m / "results.json"
            if p.exists():
                p.unlink()
        with self._lock:
            self._status = self._idle_status()
        log.info("experiment data reset (on-chain records are immutable and remain on the chain)")
        return self.status()

    # ------------------------------------------------------------ execution
    def _run_queue(self, queue: list[str], settings: dict) -> None:
        try:
            for i, mode in enumerate(queue):
                if self._stop.is_set():
                    raise StopRequested()
                self._set(queue=queue[i:])
                exp_id = self.run_experiment(mode, settings)
                with self._lock:
                    self._status["completed_experiments"].append({"mode": mode, "experiment_id": exp_id})
            self._set(state="completed", phase="done", finished_at=db.now(), queue=[])
            self._log("All experiments completed.")
        except StopRequested:
            self._set(state="stopped", phase=None, finished_at=db.now())
            self._log("Training stopped by user.", "warning")
        except Exception as e:  # noqa: BLE001 - surface any failure to the UI
            log.exception("experiment job failed")
            self._set(state="failed", error=str(e), finished_at=db.now())
            self._log(f"Experiment failed: {e}", "warning")

    def run_experiment(self, mode: str, settings: dict) -> str:
        """Run one experiment synchronously (used by the job thread and tests)."""
        cfg = build_config(mode, settings)
        cfg.validate()
        exp_id = f"{mode}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        data = load_federated_dataset(config.CLIENT_NAMES, seed=cfg.seed, strategy=cfg.partition,
                                      alpha=cfg.dirichlet_alpha)
        use_chain = bool(settings.get("blockchain_enabled", True)) and mode != "centralized"
        chain_status = "disabled" if not use_chain else "pending"
        if use_chain:
            if self.chain.ready or self.chain.connect():
                try:
                    self.register_all_on_chain()
                    chain_status = "connected"
                except BlockchainError as e:
                    chain_status = "unavailable"
                    self._log(f"Blockchain registration failed: {e}", "warning")
            else:
                chain_status = "unavailable"
                self._log(f"Blockchain unavailable - experiment will run WITHOUT on-chain audit: "
                          f"{self.chain.last_error}", "warning")

        db.insert("experiment_results", {
            "id": exp_id, "mode": mode, "status": "running", "config": cfg.to_dict(),
            "started_at": db.now(), "blockchain_status": chain_status,
        })
        self._set(experiment_id=exp_id, mode_current=mode, total_rounds=cfg.rounds, current_round=0,
                  clients={c.name: {"status": "idle", "epoch": 0, "epochs": cfg.local_epochs, "progress": 0.0}
                           for c in data.clients})
        self._log(f"Starting {mode} experiment {exp_id} (attack={'on' if cfg.attack.enabled else 'off'}, "
                  f"defense={'on' if cfg.defense_enabled else 'off'}, blockchain={chain_status})")
        handler = _EventHandler(self, exp_id, cfg, use_chain and chain_status == "connected")
        try:
            if mode == "centralized":
                result = run_centralized(cfg, data, handler, self._stop.is_set)
            else:
                result = run_federated(cfg, data, handler, self._stop.is_set)
        except StopRequested:
            db.update("experiment_results", {"id": exp_id}, {"status": "stopped", "finished_at": db.now()})
            raise
        except Exception as e:
            db.update("experiment_results", {"id": exp_id},
                      {"status": "failed", "error": str(e), "finished_at": db.now()})
            raise
        result.pop("final_global_vector", None)
        failed_tx = db.query_one("SELECT COUNT(*) AS n FROM blockchain_transactions WHERE experiment_id = ? "
                                 "AND status = 'failed'", [exp_id])["n"]
        if chain_status == "connected" and failed_tx:
            chain_status = f"partial ({failed_tx} failed tx)"
        db.update("experiment_results", {"id": exp_id}, {
            "status": "completed", "initial_metrics": result["initial_metrics"],
            "final_metrics": result["final_metrics"], "detection": result.get("detection"),
            "trust": result.get("trust"), "final_global_hash": result["final_global_hash"],
            "duration_seconds": result["duration_seconds"], "finished_at": db.now(),
            "blockchain_status": chain_status,
        })
        self._write_experiment_file(mode, exp_id, result)
        self._log(f"{mode} experiment finished: accuracy={result['final_metrics']['accuracy']:.4f}, "
                  f"f1={result['final_metrics']['f1']:.4f}")
        return exp_id

    def _write_experiment_file(self, mode: str, exp_id: str, result: dict) -> None:
        folder = config.EXPERIMENTS_DIR / mode
        folder.mkdir(parents=True, exist_ok=True)
        payload = {"experiment_id": exp_id, **result}
        (folder / "results.json").write_text(json.dumps(payload, indent=2, default=float))

    # --------------------------------------------------------------- chain
    def _record_tx(self, exp_id, round_number, chain_round_id, client, tx_type, receipt=None, error=None,
                   **extra) -> dict:
        row = {
            "experiment_id": exp_id, "round_number": round_number, "chain_round_id": chain_round_id,
            "client_name": client, "tx_type": tx_type, "contract_address": self.chain.address, **extra,
        }
        if receipt is not None:
            row.update(tx_hash=receipt["transactionHash"], block_number=receipt["blockNumber"],
                       from_address=receipt["from"], gas_used=receipt["gasUsed"], status="confirmed")
        else:
            row.update(status="failed", error=str(error) if error else "unknown error",
                       tx_hash=getattr(error, "tx_hash", None))
        row["id"] = db.insert("blockchain_transactions", row)
        return row


class _EventHandler:
    """Callable passed as ``emit`` to the training engine."""

    def __init__(self, svc: ExperimentService, exp_id: str, cfg: ExperimentConfig, use_chain: bool):
        self.svc = svc
        self.exp_id = exp_id
        self.cfg = cfg
        self.use_chain = use_chain
        self.chain_round: dict[int, Optional[int]] = {}
        self.update_ids: dict[tuple[int, str], int] = {}
        self.art_dir = config.ARTIFACT_DIR / exp_id
        self.client_index = {n: i for i, n in enumerate(config.CLIENT_NAMES)}

    def __call__(self, event: str, p: dict) -> None:
        getattr(self, f"on_{event}", lambda _p: None)(p)

    def _chain(self, round_number, client, tx_type, fn, **extra):
        """Run a blockchain call; persist confirmed/failed result. Returns receipt or None."""
        crid = self.chain_round.get(round_number)
        try:
            rc = fn()
            self.svc._record_tx(self.exp_id, round_number, crid, client, tx_type, rc, **extra)
            return rc
        except BlockchainError as e:
            self.svc._record_tx(self.exp_id, round_number, crid, client, tx_type, None, error=e, **extra)
            self.svc._log(f"Blockchain {tx_type} failed (round {round_number}, {client or 'coordinator'}): {e}",
                          "warning")
            return None

    # ---- federated events
    def on_round_started(self, p):
        r = p["round"]
        self.svc._set(current_round=r, phase="local_training")
        for name in config.CLIENT_NAMES:
            self.svc._client_state(name, status="waiting", epoch=0, progress=0.0)
        rd = self.art_dir / f"round_{r}"
        rd.mkdir(parents=True, exist_ok=True)
        np.save(rd / "global_before.npy", p["global_vector"])
        crid = None
        if self.use_chain:
            try:
                crid, rc = self.svc.chain.start_round(self.exp_id, r)
                self.chain_round[r] = crid
                self.svc._record_tx(self.exp_id, r, crid, None, "start_round", rc)
            except BlockchainError as e:
                self.chain_round[r] = None
                self.svc._record_tx(self.exp_id, r, None, None, "start_round", None, error=e)
                self.svc._log(f"Blockchain start_round failed (round {r}): {e}", "warning")
        db.insert("training_rounds", {"experiment_id": self.exp_id, "round_number": r, "chain_round_id": crid,
                                      "global_hash_before": p["global_hash"]})
        self.svc._log(f"Round {r}/{self.cfg.rounds}: global model {p['global_hash'][:18]}... sent to participants")

    def on_client_progress(self, p):
        self.svc._client_state(p["client"], status="training", epoch=p["epoch"], epochs=p["epochs"],
                               progress=p["epoch"] / p["epochs"])

    def on_update_submitted(self, p):
        r, client = p["round"], p["client"]
        path = self.art_dir / f"round_{r}" / f"{slug(client)}.npy"
        np.save(path, p["delta"])
        uid = db.insert("model_updates", {
            "experiment_id": self.exp_id, "round_number": r, "client_name": client,
            "update_hash": p["update_hash"], "num_samples": p["num_samples"], "is_malicious": p["is_malicious"],
            "local_accuracy": p["local_accuracy"], "epoch_losses": p["epoch_losses"],
            "attack_details": p["attack_details"], "artifact_path": str(path.relative_to(config.ARTIFACT_DIR)),
        })
        self.update_ids[(r, client)] = uid
        self.svc._client_state(client, status="submitted", progress=1.0, update_hash=p["update_hash"])
        self.svc._log(f"{client} submitted update {p['update_hash'][:18]}..." +
                      (" [ATTACK ACTIVE]" if p["is_malicious"] else ""))
        crid = self.chain_round.get(r)
        if self.use_chain and crid is not None:
            idx = self.client_index[client]
            self._chain(r, client, "submit_update", lambda: self.svc.chain.submit_update(idx, crid, p["update_hash"]),
                        update_hash=p["update_hash"])

    def on_round_analyzed(self, p):
        r = p["round"]
        self.svc._set(phase="security_analysis")
        crid = self.chain_round.get(r)
        for a in p["analyses"]:
            client = a["client"]
            included = a["aggregation_weight"] > 0 if self.cfg.defense_enabled else True
            uid = self.update_ids.get((r, client))
            db.insert("security_analysis", {
                "update_id": uid, "experiment_id": self.exp_id, "round_number": r, "client_name": client,
                **{k: a[k] for k in ("l2_norm", "norm_per_step", "local_steps", "norm_z", "cosine_similarity",
                                     "weight_deviation", "validation_loss", "validation_loss_baseline",
                                     "norm_anomaly", "cosine_disagreement", "deviation_score", "validation_impact",
                                     "isolation_score", "detector_mode", "risk_score", "decision",
                                     "explanation")},
                "enforced": self.cfg.defense_enabled, "aggregation_weight": a["aggregation_weight"],
            })
            if uid:
                db.update("model_updates", {"id": uid}, {"included": included,
                                                        "aggregation_weight": a["aggregation_weight"]})
            t = p["trust"].get(client, {})
            db.insert("trust_history", {
                "experiment_id": self.exp_id, "round_number": r, "client_name": client,
                "trust_score": t.get("trust", 50.0), "ema_risk": t.get("ema_risk"), "accepted": t.get("accepted"),
                "suspicious": t.get("suspicious"), "rejected": t.get("rejected"),
            })
            self.svc._client_state(client, status=a["decision"].lower(), risk=a["risk_score"],
                                   decision=a["decision"], included=included, trust=t.get("trust"))
            self.svc._log(f"Security engine: {client} risk={a['risk_score']:.3f} -> {a['decision']}"
                          + ("" if self.cfg.defense_enabled or a["decision"] == "ACCEPT" else " (defense off: aggregated anyway)"))
            if self.use_chain and crid is not None:
                idx = self.client_index[client]
                self._chain(r, client, "record_decision",
                            lambda: self.svc.chain.record_decision(crid, idx, a["risk_score"], a["decision"], included),
                            update_hash=db.query_one("SELECT update_hash FROM model_updates WHERE id = ?", [uid])["update_hash"] if uid else None,
                            risk_score_bps=int(round(a["risk_score"] * 10_000)), decision=a["decision"],
                            included=included)

    def on_round_completed(self, p):
        r = p["round"]
        self.svc._set(phase="aggregation")
        np.save(self.art_dir / f"round_{r}" / "global_after.npy", p["global_vector"])
        m = p["metrics"]
        db.update("training_rounds", {"experiment_id": self.exp_id, "round_number": r}, {
            "global_hash": p["global_hash"], "accuracy": m["accuracy"], "precision_score": m["precision"],
            "recall": m["recall"], "f1": m["f1"], "loss": m["loss"], "train_loss": p["train_loss"],
            "included": p["included"], "excluded": p["excluded"], "effective_weights": p["effective_weights"],
        })
        self.svc._log(f"Round {r} aggregated {len(p['included'])} update(s)"
                      + (f", excluded {', '.join(p['excluded'])}" if p["excluded"] else "")
                      + f" -> test accuracy {m['accuracy']:.4f}")
        crid = self.chain_round.get(r)
        if self.use_chain and crid is not None:
            self.svc._set(phase="blockchain")
            self._chain(r, None, "finalize_round", lambda: self.svc.chain.finalize_round(crid, p["global_hash"]),
                        update_hash=p["global_hash"])

    # ---- centralized baseline
    def on_centralized_round(self, p):
        r = p["round"]
        self.svc._set(current_round=r, phase="centralized_training")
        m = p["metrics"]
        db.insert("training_rounds", {
            "experiment_id": self.exp_id, "round_number": r, "global_hash": p["global_hash"],
            "accuracy": m["accuracy"], "precision_score": m["precision"], "recall": m["recall"], "f1": m["f1"],
            "loss": m["loss"], "train_loss": p["train_loss"], "included": [], "excluded": [],
        })
        self.svc._log(f"Centralized baseline epoch-block {r}: accuracy {m['accuracy']:.4f}")


service = ExperimentService()
