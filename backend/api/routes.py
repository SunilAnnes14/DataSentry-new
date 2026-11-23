"""REST API routes."""
from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query

import config
from api.schemas import (HealthResponse, RegisterClientRequest, Settings, StartTrainingRequest,
                         SubmitUpdateRequest, SubmitUpdateResponse, TrainingStatus)
from core import database as db
from core.blockchain_service import BlockchainError
from core.experiment_service import service, slug
from core.security_engine import SecurityConfig, SecurityEngine
from datasets.prepare_data import load_federated_dataset
from models.neural_network import create_model, get_params, hash_params, num_parameters, unflatten

log = logging.getLogger("datasentry.api")
router = APIRouter(prefix="/api")
VERSION = "1.0.0"

_TEMPLATE = get_params(create_model(0))


def _latest_experiment(experiment_id: Optional[str] = None, federated_only: bool = True) -> Optional[dict]:
    if experiment_id:
        row = db.query_one("SELECT * FROM experiment_results WHERE id = ?", [experiment_id])
        if row is None:
            raise HTTPException(404, f"experiment {experiment_id} not found")
        return row
    sql = "SELECT * FROM experiment_results"
    if federated_only:
        sql += " WHERE mode != 'centralized'"
    return db.query_one(sql + " ORDER BY started_at DESC LIMIT 1")


# ------------------------------------------------------------------ health
@router.get("/health", response_model=HealthResponse, tags=["system"])
def health():
    try:
        db.query_one("SELECT 1 AS ok")
        db_ok = True
    except Exception:
        db_ok = False
    chain = service.chain.status()
    return {
        "status": "ok" if db_ok and chain["connected"] else "degraded",
        "version": VERSION,
        "database": db_ok,
        "training_state": service.status()["state"],
        "blockchain": chain,
    }


@router.get("/overview", tags=["system"])
def overview():
    st = service.status()
    clients = db.query("SELECT name, wallet_address, registered_on_chain, num_samples FROM clients ORDER BY id")
    totals = db.query_one("""SELECT
        (SELECT COUNT(*) FROM model_updates WHERE source = 'training') AS updates,
        (SELECT COUNT(*) FROM security_analysis WHERE decision != 'ACCEPT') AS threats,
        (SELECT COUNT(*) FROM security_analysis WHERE decision = 'REJECT') AS rejected,
        (SELECT COUNT(*) FROM security_analysis WHERE decision = 'SUSPICIOUS') AS suspicious,
        (SELECT COUNT(*) FROM security_analysis WHERE decision = 'ACCEPT') AS accepted,
        (SELECT COUNT(*) FROM blockchain_transactions WHERE status = 'confirmed') AS tx_confirmed,
        (SELECT COUNT(*) FROM blockchain_transactions WHERE status = 'failed') AS tx_failed,
        (SELECT COUNT(*) FROM experiment_results WHERE status = 'completed') AS experiments""")
    latest = db.query_one("SELECT * FROM experiment_results WHERE status = 'completed' AND mode != 'centralized' "
                          "ORDER BY finished_at DESC LIMIT 1")
    last_decisions = {}
    if latest:
        for r in db.query("""SELECT client_name, decision, risk_score FROM security_analysis
                             WHERE experiment_id = ? AND round_number = (SELECT MAX(round_number)
                             FROM security_analysis WHERE experiment_id = ?)""", [latest["id"], latest["id"]]):
            last_decisions[r["client_name"]] = {"decision": r["decision"], "risk": r["risk_score"]}
    chain = service.chain.status()
    return {
        "active_organizations": sum(1 for c in clients if c["registered_on_chain"]) or len(clients),
        "organizations": [{**c, **last_decisions.get(c["name"], {}),
                           "live": st["clients"].get(c["name"])} for c in clients],
        "training": {"state": st["state"], "mode": st["mode"], "current_round": st["current_round"],
                     "total_rounds": st["total_rounds"], "phase": st["phase"]},
        "totals": totals,
        "latest_experiment": latest and {k: latest[k] for k in ("id", "mode", "final_metrics", "finished_at",
                                                                 "blockchain_status")},
        "blockchain": chain,
    }


# ----------------------------------------------------------------- clients
@router.get("/clients", tags=["clients"])
def list_clients():
    rows = db.query("SELECT * FROM clients ORDER BY id")
    stats = {r["client_name"]: r for r in db.query("""SELECT client_name, COUNT(*) AS updates,
        SUM(decision = 'ACCEPT') AS accepted, SUM(decision = 'SUSPICIOUS') AS suspicious,
        SUM(decision = 'REJECT') AS rejected FROM security_analysis GROUP BY client_name""")}
    st = service.status()["clients"]
    return [{**r, "stats": stats.get(r["name"], {"updates": 0, "accepted": 0, "suspicious": 0, "rejected": 0}),
             "live": st.get(r["name"])} for r in rows]


@router.post("/clients/register", tags=["clients"])
def register_client(req: RegisterClientRequest):
    if req.name not in config.CLIENT_NAMES:
        raise HTTPException(422, f"unknown organisation; this prototype simulates {config.CLIENT_NAMES} "
                                 "(each needs a local data partition and a wallet)")
    if db.query_one("SELECT id FROM clients WHERE name = ?", [req.name]) is None:
        db.insert("clients", {"name": req.name, "organization_type": req.organization_type})
    try:
        result = service.register_client_on_chain(config.CLIENT_NAMES.index(req.name), req.name)
    except BlockchainError as e:
        raise HTTPException(503, f"on-chain registration failed: {e}")
    return result


# ---------------------------------------------------------------- settings
@router.get("/settings", tags=["settings"])
def get_settings():
    return service.settings.get()


@router.put("/settings", tags=["settings"])
def put_settings(s: Settings):
    try:
        return service.settings.save(s.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/settings/reset", tags=["settings"])
def reset_settings():
    return service.settings.reset()


# ---------------------------------------------------------------- training
@router.post("/training/start", response_model=TrainingStatus, tags=["training"])
def start_training(req: StartTrainingRequest):
    if req.settings:
        merged = service.settings.get()
        for k, v in req.settings.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k].update(v)
            else:
                merged[k] = v
        try:
            Settings(**merged)
        except Exception as e:
            raise HTTPException(422, f"invalid settings override: {e}")
    try:
        return service.start(req.mode, req.settings)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/training/stop", response_model=TrainingStatus, tags=["training"])
def stop_training():
    try:
        return service.stop()
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.post("/training/reset", response_model=TrainingStatus, tags=["training"])
def reset_training():
    try:
        return service.reset()
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.get("/training/status", response_model=TrainingStatus, tags=["training"])
def training_status():
    return service.status()


@router.get("/training/rounds", tags=["training"])
def training_rounds(experiment_id: Optional[str] = None):
    exp = _latest_experiment(experiment_id, federated_only=False)
    if not exp:
        return {"experiment": None, "rounds": []}
    rounds = db.query("SELECT * FROM training_rounds WHERE experiment_id = ? ORDER BY round_number", [exp["id"]])
    updates = db.query("""SELECT u.*, s.risk_score, s.decision FROM model_updates u
        LEFT JOIN security_analysis s ON s.update_id = u.id WHERE u.experiment_id = ? AND u.source = 'training'
        ORDER BY u.round_number, u.id""", [exp["id"]])
    for r in rounds:
        r["updates"] = [u for u in updates if u["round_number"] == r["round_number"]]
    return {"experiment": exp, "rounds": rounds}


@router.get("/experiments", tags=["training"])
def list_experiments(limit: int = Query(50, ge=1, le=500)):
    return db.query("SELECT * FROM experiment_results ORDER BY started_at DESC LIMIT ?", [limit])


@router.get("/experiments/{experiment_id}", tags=["training"])
def get_experiment(experiment_id: str):
    return training_rounds(experiment_id)


# ----------------------------------------------------------------- updates
@router.post("/updates/submit", response_model=SubmitUpdateResponse, tags=["updates"])
def submit_update(req: SubmitUpdateRequest):
    """Screen an externally supplied model update with the AI security engine.

    The update is compared against the stored updates of the other
    participants from a reference round (default: latest round of the latest
    federated experiment) and against that round's starting global model.
    """
    expected = num_parameters(_TEMPLATE)
    if len(req.update) != expected:
        raise HTTPException(422, f"update must contain exactly {expected} values (DSv1 parameter order)")
    vec = np.asarray(req.update, dtype=np.float32)
    if not np.all(np.isfinite(vec)):
        raise HTTPException(422, "update contains NaN or infinite values")
    exp = _latest_experiment(req.experiment_id)
    if exp is None:
        raise HTTPException(409, "no federated experiment available as reference; run training first")
    rnd = req.round_number or db.query_one("SELECT MAX(round_number) AS r FROM model_updates WHERE experiment_id = ? "
                                           "AND source = 'training'", [exp["id"]])["r"]
    if not rnd:
        raise HTTPException(409, "reference experiment has no stored updates")
    rdir = config.ARTIFACT_DIR / exp["id"] / f"round_{rnd}"
    gpath = rdir / "global_before.npy"
    if not gpath.exists():
        raise HTTPException(409, "reference round artifacts are missing")
    peers = db.query("SELECT client_name, num_samples, artifact_path FROM model_updates WHERE experiment_id = ? AND "
                     "round_number = ? AND source = 'training' AND client_name != ?", [exp["id"], rnd, req.client_name])
    names, deltas, steps = [], [], []
    cfg = exp["config"]
    for p in peers:
        names.append(p["client_name"])
        deltas.append(np.load(config.ARTIFACT_DIR / p["artifact_path"]))
        steps.append(cfg["local_epochs"] * math.ceil(p["num_samples"] / cfg["batch_size"]))
    names.append(req.client_name)
    deltas.append(vec)
    steps.append(cfg["local_epochs"] * math.ceil(req.num_samples / cfg["batch_size"]))

    sec_cfg = SecurityConfig(**{**SecurityConfig().to_dict(), **service.settings.get()["security"]})
    engine = SecurityEngine(sec_cfg, seed=cfg["seed"])
    engine.history = [[h["norm_anomaly"], h["cosine_disagreement"], h["deviation_score"], h["validation_impact"]]
                      for h in db.query("SELECT * FROM security_analysis WHERE experiment_id = ? AND round_number < ? "
                                        "AND decision = 'ACCEPT'", [exp["id"], rnd])]
    data = load_federated_dataset(config.CLIENT_NAMES, seed=cfg["seed"], strategy=cfg["partition"],
                                  alpha=cfg["dirichlet_alpha"])
    analysis = engine.analyze(names, deltas, np.load(gpath), _TEMPLATE, data.X_val, data.y_val,
                              enforce=True, record_history=False, local_steps=steps)[-1]
    upd_hash = hash_params(unflatten(vec, _TEMPLATE))
    uid = db.insert("model_updates", {
        "experiment_id": exp["id"], "round_number": rnd, "client_name": req.client_name, "update_hash": upd_hash,
        "num_samples": req.num_samples, "source": "api", "included": False,
        "aggregation_weight": analysis.aggregation_weight,
    })
    a = analysis.to_dict()
    db.insert("security_analysis", {
        "update_id": uid, "experiment_id": exp["id"], "round_number": rnd, "client_name": req.client_name,
        **{k: a[k] for k in a if k not in ("client",)}, "enforced": True,
    })
    return {"update_id": uid, "update_hash": upd_hash, "reference_experiment": exp["id"], "reference_round": rnd,
            "analysis": a,
            "note": "Screening only: the reference round is already finalized on-chain, so this update is not "
                    "aggregated or recorded as a transaction."}


@router.get("/updates/{update_id}/verify", tags=["updates"])
def verify_update(update_id: int):
    """Recompute the SHA-256 of the stored update artifact and compare with DB and chain."""
    u = db.query_one("SELECT * FROM model_updates WHERE id = ?", [update_id])
    if u is None:
        raise HTTPException(404, "update not found")
    if not u["artifact_path"]:
        raise HTTPException(409, "update has no stored artifact (API screening submissions are not stored)")
    path = config.ARTIFACT_DIR / u["artifact_path"]
    if not path.exists():
        raise HTTPException(410, "artifact file no longer exists")
    recomputed = hash_params(unflatten(np.load(path), _TEMPLATE))
    out = {"update_id": update_id, "client_name": u["client_name"], "stored_hash": u["update_hash"],
           "recomputed_hash": recomputed, "matches_database": recomputed == u["update_hash"], "on_chain": None}
    rnd = db.query_one("SELECT chain_round_id FROM training_rounds WHERE experiment_id = ? AND round_number = ?",
                       [u["experiment_id"], u["round_number"]])
    client = db.query_one("SELECT wallet_address FROM clients WHERE name = ?", [u["client_name"]])
    if rnd and rnd["chain_round_id"] and client and client["wallet_address"]:
        try:
            rec = service.chain.get_update(rnd["chain_round_id"], client["wallet_address"])
            out["on_chain"] = {**rec, "matches_chain": rec["update_hash"] == recomputed}
        except Exception as e:
            out["on_chain"] = {"error": str(e)}
    return out


# ---------------------------------------------------------------- security
@router.get("/security/analysis", tags=["security"])
def security_analysis(experiment_id: Optional[str] = None, round_number: Optional[int] = Query(None, alias="round")):
    exp = _latest_experiment(experiment_id)
    if not exp:
        return {"experiment": None, "analyses": [], "thresholds": service.settings.get()["security"]}
    sql = """SELECT s.*, u.update_hash, u.is_malicious, u.num_samples, u.included,
        (SELECT tx_hash FROM blockchain_transactions t WHERE t.experiment_id = s.experiment_id AND
         t.round_number = s.round_number AND t.client_name = s.client_name AND t.tx_type = 'record_decision'
         AND t.status = 'confirmed' LIMIT 1) AS decision_tx
        FROM security_analysis s LEFT JOIN model_updates u ON u.id = s.update_id
        WHERE s.experiment_id = ? AND (u.source IS NULL OR u.source = 'training')"""
    params: list = [exp["id"]]
    if round_number:
        sql += " AND s.round_number = ?"
        params.append(round_number)
    rows = db.query(sql + " ORDER BY s.round_number, s.id", params)
    alerts = [r for r in rows if r["decision"] != "ACCEPT"]
    return {"experiment": {k: exp[k] for k in ("id", "mode", "status", "config", "detection")},
            "analyses": rows, "alerts": alerts, "thresholds": exp["config"]["security"]}


@router.get("/security/clients", tags=["security"])
def security_clients(experiment_id: Optional[str] = None):
    exp = _latest_experiment(experiment_id)
    clients = [c["name"] for c in db.query("SELECT name FROM clients ORDER BY id")] or config.CLIENT_NAMES
    out = []
    for name in clients:
        hist = db.query("SELECT round_number, trust_score, ema_risk, accepted, suspicious, rejected "
                        "FROM trust_history WHERE experiment_id = ? AND client_name = ? ORDER BY round_number",
                        [exp["id"] if exp else "", name])
        risks = db.query("SELECT s.round_number, s.risk_score, s.decision FROM security_analysis s JOIN model_updates u "
                         "ON u.id = s.update_id WHERE s.experiment_id = ? AND s.client_name = ? AND u.source = "
                         "'training' ORDER BY s.round_number", [exp["id"] if exp else "", name])
        last = hist[-1] if hist else None
        alltime = db.query_one("""SELECT COUNT(*) AS updates, COALESCE(SUM(decision='ACCEPT'),0) AS accepted,
            COALESCE(SUM(decision='SUSPICIOUS'),0) AS suspicious, COALESCE(SUM(decision='REJECT'),0) AS rejected
            FROM security_analysis s JOIN model_updates u ON u.id = s.update_id
            WHERE s.client_name = ? AND u.source = 'training'""", [name])
        out.append({
            "client_name": name,
            "trust_score": last["trust_score"] if last else 50.0,
            "accepted": last["accepted"] if last else 0,
            "suspicious": last["suspicious"] if last else 0,
            "rejected": last["rejected"] if last else 0,
            "trust_history": [{"round": 0, "trust_score": 50.0}] + [
                {"round": h["round_number"], "trust_score": h["trust_score"]} for h in hist],
            "risk_history": risks,
            "all_time": alltime,
        })
    return {"experiment_id": exp["id"] if exp else None, "neutral_trust": 50.0, "clients": out}


# -------------------------------------------------------------- blockchain
@router.get("/blockchain/status", tags=["blockchain"])
def blockchain_status():
    return service.chain.status()


@router.post("/blockchain/connect", tags=["blockchain"])
def blockchain_connect():
    ok = service.chain.connect()
    if ok:
        try:
            service.register_all_on_chain()
        except BlockchainError as e:
            raise HTTPException(503, str(e))
    return service.chain.status()


@router.get("/blockchain/contract", tags=["blockchain"])
def blockchain_contract():
    """Public contract info so the frontend can verify records directly with ethers.js."""
    st = service.chain.status()
    try:
        abi = service.chain.abi()
    except BlockchainError as e:
        raise HTTPException(503, str(e))
    return {"address": st["contract_address"], "chain_id": st["chain_id"], "rpc_url": config.PUBLIC_RPC_URL, "abi": abi}


@router.get("/blockchain/records", tags=["blockchain"])
def blockchain_records(experiment_id: Optional[str] = None, tx_type: Optional[str] = None,
                       status: Optional[str] = None, limit: int = Query(200, ge=1, le=2000)):
    sql = """SELECT t.*, e.mode AS experiment_mode, c.wallet_address AS client_wallet
             FROM blockchain_transactions t
             LEFT JOIN experiment_results e ON e.id = t.experiment_id
             LEFT JOIN clients c ON c.name = t.client_name WHERE 1=1"""
    params: list = []
    for col, val in (("t.experiment_id", experiment_id), ("t.tx_type", tx_type), ("t.status", status)):
        if val:
            sql += f" AND {col} = ?"
            params.append(val)
    sql += " ORDER BY t.id DESC LIMIT ?"
    params.append(limit)
    return db.query(sql, params)


@router.get("/blockchain/transactions/{tx_hash}", tags=["blockchain"])
def blockchain_transaction(tx_hash: str):
    row = db.query_one("""SELECT t.*, e.mode AS experiment_mode, c.wallet_address AS client_wallet
        FROM blockchain_transactions t LEFT JOIN experiment_results e ON e.id = t.experiment_id
        LEFT JOIN clients c ON c.name = t.client_name WHERE t.tx_hash = ?""", [tx_hash])
    if row is None:
        raise HTTPException(404, "transaction not found in DataSentry records")
    out = {"record": row, "chain": None, "on_chain_state": None}
    try:
        out["chain"] = service.chain.get_transaction(tx_hash)
        if row["chain_round_id"]:
            if row["tx_type"] in ("submit_update", "record_decision") and row["client_wallet"]:
                out["on_chain_state"] = service.chain.get_update(row["chain_round_id"], row["client_wallet"])
            elif row["tx_type"] in ("start_round", "finalize_round"):
                out["on_chain_state"] = service.chain.get_round(row["chain_round_id"])
    except Exception as e:
        out["chain_error"] = str(e)
    return out


# ------------------------------------------------------------------- model
@router.get("/model/metrics", tags=["model"])
def model_metrics():
    """Latest completed experiment per mode, with per-round curves."""
    comparison = {}
    for mode in ("centralized", "clean", "poisoned", "protected", "custom"):
        exp = db.query_one("SELECT * FROM experiment_results WHERE mode = ? AND status = 'completed' "
                           "ORDER BY finished_at DESC LIMIT 1", [mode])
        if not exp:
            continue
        rounds = db.query("SELECT round_number, accuracy, precision_score, recall, f1, loss, train_loss, "
                          "included, excluded FROM training_rounds WHERE experiment_id = ? ORDER BY round_number",
                          [exp["id"]])
        comparison[mode] = {
            "experiment_id": exp["id"], "finished_at": exp["finished_at"], "initial_metrics": exp["initial_metrics"],
            "final_metrics": exp["final_metrics"], "detection": exp["detection"], "rounds": rounds,
            "attack": exp["config"]["attack"] if exp["config"]["attack"]["enabled"] and mode != "centralized" else None,
            "defense_enabled": exp["config"]["defense_enabled"], "duration_seconds": exp["duration_seconds"],
            "blockchain_status": exp["blockchain_status"],
        }
    data = load_federated_dataset(config.CLIENT_NAMES, seed=service.settings.get()["seed"])
    return {"comparison": comparison, "dataset": data.summary(),
            "positive_class": "malignant (precision/recall/F1 computed for malignant detection)"}
