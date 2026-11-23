"""Integration tests: full engine runs, persistence, API responses and
(when a local Hardhat node is reachable) the on-chain audit trail."""
import math

import numpy as np
import pytest
import requests  # noqa: F401  (installed with web3)
from fastapi.testclient import TestClient

import config
from core import database as db
from core.blockchain_service import BlockchainService
from core.experiment_service import DEFAULT_SETTINGS, ExperimentService
from core.training_engine import ExperimentConfig, run_federated
from core.attack_simulator import AttackConfig
from datasets.prepare_data import load_federated_dataset

ATTACK = {"enabled": True, "target_client": "Hospital Delta", "attack_type": "label_flip_scaled",
          "flip_rate": 1.0, "strength": 3.0}


def _settings(**kw):
    import copy
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s.update({"rounds": 1, "blockchain_enabled": False, "attack": dict(ATTACK)})
    s.update(kw)
    return s


@pytest.fixture(scope="module")
def client():
    from main import app
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------ engine level
def test_one_clean_round_and_one_poisoned_round():
    data = load_federated_dataset(config.CLIENT_NAMES, seed=42)
    clean = run_federated(ExperimentConfig(rounds=1, defense_enabled=True), data)
    assert clean["rounds"][0]["excluded"] == []
    assert clean["final_metrics"]["accuracy"] > 0.85
    poisoned = run_federated(ExperimentConfig(rounds=1, defense_enabled=False,
                                              attack=AttackConfig(**ATTACK)), data)
    protected = run_federated(ExperimentConfig(rounds=1, defense_enabled=True,
                                               attack=AttackConfig(**ATTACK)), data)
    delta = [a for a in protected["rounds"][0]["analyses"] if a["client"] == "Hospital Delta"][0]
    assert delta["decision"] == "REJECT"
    assert protected["rounds"][0]["excluded"] == ["Hospital Delta"]
    assert "Hospital Delta" in poisoned["rounds"][0]["included"]       # undefended baseline aggregates it
    assert protected["final_metrics"]["accuracy"] > poisoned["final_metrics"]["accuracy"] + 0.2
    # reproducibility: same seed -> identical global model hash
    again = run_federated(ExperimentConfig(rounds=1, defense_enabled=True, attack=AttackConfig(**ATTACK)), data)
    assert again["final_global_hash"] == protected["final_global_hash"]


def test_excluded_update_does_not_enter_aggregation():
    """The protected global model must equal FedAvg over the accepted updates only."""
    from core.aggregation import AggregationInput, fedavg
    data = load_federated_dataset(config.CLIENT_NAMES, seed=42)
    captured = {}

    def emit(event, p):
        if event == "round_started":
            captured["g"] = p["global_vector"].copy()
        elif event == "update_submitted":
            captured.setdefault("updates", []).append((p["client"], p["delta"], p["num_samples"]))
        elif event == "round_completed":
            captured["new"] = p["global_vector"].copy()

    run_federated(ExperimentConfig(rounds=1, attack=AttackConfig(**ATTACK)), data, emit)
    honest = [AggregationInput(c, d, n, 1.0, "ACCEPT") for c, d, n in captured["updates"] if c != "Hospital Delta"]
    expected = fedavg(captured["g"], honest).new_global
    assert np.allclose(captured["new"], expected, atol=1e-6)


# --------------------------------------------------------- service + db
def test_service_persists_experiment_without_blockchain():
    db.init_db()
    svc = ExperimentService(chain=BlockchainService(rpc_url="http://127.0.0.1:1"))
    exp_id = svc.run_experiment("protected", _settings())
    exp = db.query_one("SELECT * FROM experiment_results WHERE id = ?", [exp_id])
    assert exp["status"] == "completed" and exp["blockchain_status"] == "disabled"
    rows = db.query("SELECT * FROM security_analysis WHERE experiment_id = ?", [exp_id])
    assert len(rows) == 4
    rej = [r for r in rows if r["decision"] == "REJECT"]
    assert [r["client_name"] for r in rej] == ["Hospital Delta"]
    upd = db.query_one("SELECT * FROM model_updates WHERE experiment_id = ? AND client_name = 'Hospital Delta'",
                       [exp_id])
    assert upd["included"] == 0 and upd["is_malicious"] == 1
    rnd = db.query_one("SELECT * FROM training_rounds WHERE experiment_id = ?", [exp_id])
    assert rnd["excluded"] == ["Hospital Delta"]
    assert len(db.query("SELECT * FROM trust_history WHERE experiment_id = ?", [exp_id])) == 4
    assert (config.EXPERIMENTS_DIR / "protected" / "results.json").exists()


# ------------------------------------------------------------------- API
def test_health_and_validation(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] is True and body["status"] in ("ok", "degraded")
    assert client.get("/api/clients").json()[0]["name"] == "Hospital Alpha"
    bad = client.put("/api/settings", json={**_settings(), "security": {"accept_threshold": 0.9,
                                                                       "reject_threshold": 0.5}})
    assert bad.status_code == 422
    assert client.post("/api/training/start", json={"mode": "bogus"}).status_code == 422
    assert client.post("/api/training/stop").status_code == 409


def test_api_training_flow_returns_real_results(client):
    """Start a job through the API, poll to completion, and check every page's endpoint."""
    import time
    assert client.put("/api/settings", json=_settings()).status_code == 200
    r = client.post("/api/training/start", json={"mode": "protected"})
    assert r.status_code == 200 and r.json()["state"] == "running"
    for _ in range(300):
        st = client.get("/api/training/status").json()
        if st["state"] not in ("running", "stopping"):
            break
        time.sleep(0.2)
    assert st["state"] == "completed", st
    exp_id = st["completed_experiments"][0]["experiment_id"]

    sec = client.get("/api/security/analysis").json()
    assert sec["experiment"]["id"] == exp_id
    delta = [a for a in sec["analyses"] if a["client_name"] == "Hospital Delta"][0]
    db_row = db.query_one("SELECT risk_score FROM security_analysis WHERE experiment_id = ? AND "
                          "client_name = 'Hospital Delta'", [exp_id])
    assert delta["risk_score"] == db_row["risk_score"] and delta["decision"] == "REJECT"
    trust = {c["client_name"]: c for c in client.get("/api/security/clients").json()["clients"]}
    assert trust["Hospital Delta"]["trust_score"] < 50 < trust["Hospital Alpha"]["trust_score"]
    metrics = client.get("/api/model/metrics").json()["comparison"]["protected"]
    exp = db.query_one("SELECT final_metrics FROM experiment_results WHERE id = ?", [exp_id])
    assert metrics["final_metrics"] == exp["final_metrics"]
    rounds = client.get("/api/training/rounds").json()
    assert rounds["experiment"]["id"] == exp_id and len(rounds["rounds"]) == 1

    # hash verification from the stored artifact
    uid = delta["update_id"]
    v = client.get(f"/api/updates/{uid}/verify").json()
    assert v["matches_database"] is True

    # external update screening: an honest peer's update vs. a sign-flipped amplified one
    alpha = db.query_one("SELECT artifact_path, num_samples FROM model_updates WHERE experiment_id = ? AND "
                         "client_name = 'Hospital Alpha'", [exp_id])
    vec = np.load(config.ARTIFACT_DIR / alpha["artifact_path"])
    ok = client.post("/api/updates/submit", json={"client_name": "Hospital Alpha", "update": vec.tolist(),
                                                  "num_samples": alpha["num_samples"]})
    assert ok.status_code == 200 and ok.json()["analysis"]["decision"] == "ACCEPT"
    evil = client.post("/api/updates/submit", json={"client_name": "Hospital Alpha", "update": (-8 * vec).tolist(),
                                                    "num_samples": alpha["num_samples"]})
    assert evil.json()["analysis"]["decision"] == "REJECT"
    assert client.post("/api/updates/submit", json={"client_name": "Hospital Alpha", "update": [0.0] * 5,
                                                    "num_samples": 5}).status_code == 422


# -------------------------------------------------------------- blockchain
def _chain():
    svc = BlockchainService()
    return svc if svc.connect() else None


@pytest.mark.skipif(_chain() is None, reason="local Hardhat node not running on 127.0.0.1:8545")
def test_blockchain_records_match_security_decisions():
    db.init_db()
    chain = _chain()
    svc = ExperimentService(chain=chain)
    for name in config.CLIENT_NAMES:
        if db.query_one("SELECT id FROM clients WHERE name = ?", [name]) is None:
            db.insert("clients", {"name": name})
    exp_id = svc.run_experiment("protected", _settings(blockchain_enabled=True))
    exp = db.query_one("SELECT * FROM experiment_results WHERE id = ?", [exp_id])
    assert exp["blockchain_status"] == "connected"
    txs = db.query("SELECT * FROM blockchain_transactions WHERE experiment_id = ?", [exp_id])
    kinds = sorted(t["tx_type"] for t in txs)
    assert kinds == sorted(["start_round"] + ["submit_update"] * 4 + ["record_decision"] * 4 + ["finalize_round"])
    assert all(t["status"] == "confirmed" and t["tx_hash"].startswith("0x") and t["block_number"] > 0 for t in txs)
    crid = db.query_one("SELECT chain_round_id FROM training_rounds WHERE experiment_id = ?", [exp_id])["chain_round_id"]
    delta_addr = chain.client_address(3)
    on_chain = chain.get_update(crid, delta_addr)
    upd = db.query_one("SELECT update_hash FROM model_updates WHERE experiment_id = ? AND client_name = "
                       "'Hospital Delta'", [exp_id])
    sec = db.query_one("SELECT risk_score FROM security_analysis WHERE experiment_id = ? AND client_name = "
                       "'Hospital Delta'", [exp_id])
    assert on_chain["update_hash"] == upd["update_hash"]
    assert on_chain["decision"] == "REJECT" and on_chain["included_in_aggregation"] is False
    assert on_chain["risk_score_bps"] == int(round(sec["risk_score"] * 10_000))
    rnd = chain.get_round(crid)
    assert rnd["status"] == "FINALIZED" and rnd["included_count"] == 3
    assert rnd["global_model_hash"] == exp["final_global_hash"]
    detail = chain.get_transaction([t for t in txs if t["tx_type"] == "record_decision"][0]["tx_hash"])
    assert detail["status"] == "confirmed" and detail["events"][0]["event"] == "UpdateDecision"
