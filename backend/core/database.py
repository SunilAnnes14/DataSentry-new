"""SQLite persistence (stdlib sqlite3, one short-lived connection per call)."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import config

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    organization_type TEXT NOT NULL DEFAULT 'hospital',
    wallet_address TEXT,
    num_samples INTEGER,
    label_counts TEXT,
    registered_on_chain INTEGER NOT NULL DEFAULT 0,
    registration_tx TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiment_results (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    config TEXT NOT NULL,
    initial_metrics TEXT,
    final_metrics TEXT,
    detection TEXT,
    trust TEXT,
    final_global_hash TEXT,
    blockchain_status TEXT,
    duration_seconds REAL,
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS training_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL REFERENCES experiment_results(id) ON DELETE CASCADE,
    round_number INTEGER NOT NULL,
    chain_round_id INTEGER,
    global_hash_before TEXT,
    global_hash TEXT,
    accuracy REAL, precision_score REAL, recall REAL, f1 REAL, loss REAL, train_loss REAL,
    included TEXT, excluded TEXT, effective_weights TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(experiment_id, round_number)
);

CREATE TABLE IF NOT EXISTS model_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL REFERENCES experiment_results(id) ON DELETE CASCADE,
    round_number INTEGER NOT NULL,
    client_name TEXT NOT NULL,
    update_hash TEXT NOT NULL,
    num_samples INTEGER NOT NULL,
    is_malicious INTEGER NOT NULL DEFAULT 0,
    local_accuracy REAL,
    epoch_losses TEXT,
    attack_details TEXT,
    artifact_path TEXT,
    included INTEGER,
    aggregation_weight REAL,
    source TEXT NOT NULL DEFAULT 'training',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS security_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    update_id INTEGER REFERENCES model_updates(id) ON DELETE CASCADE,
    experiment_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    client_name TEXT NOT NULL,
    l2_norm REAL, norm_per_step REAL, local_steps INTEGER, norm_z REAL, cosine_similarity REAL, weight_deviation REAL,
    validation_loss REAL, validation_loss_baseline REAL,
    norm_anomaly REAL, cosine_disagreement REAL, deviation_score REAL, validation_impact REAL,
    isolation_score REAL,
    detector_mode TEXT,
    risk_score REAL NOT NULL,
    decision TEXT NOT NULL,
    enforced INTEGER NOT NULL DEFAULT 1,
    aggregation_weight REAL,
    explanation TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trust_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    client_name TEXT NOT NULL,
    trust_score REAL NOT NULL,
    ema_risk REAL,
    accepted INTEGER, suspicious INTEGER, rejected INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blockchain_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT,
    round_number INTEGER,
    chain_round_id INTEGER,
    client_name TEXT,
    tx_type TEXT NOT NULL,
    tx_hash TEXT,
    block_number INTEGER,
    from_address TEXT,
    contract_address TEXT,
    gas_used INTEGER,
    status TEXT NOT NULL,
    update_hash TEXT,
    risk_score_bps INTEGER,
    decision TEXT,
    included INTEGER,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_updates_exp ON model_updates(experiment_id, round_number);
CREATE INDEX IF NOT EXISTS idx_sec_exp ON security_analysis(experiment_id, round_number);
CREATE INDEX IF NOT EXISTS idx_tx_exp ON blockchain_transactions(experiment_id);
CREATE INDEX IF NOT EXISTS idx_tx_hash ON blockchain_transactions(tx_hash);
"""

JSON_COLUMNS = {
    "label_counts", "config", "initial_metrics", "final_metrics", "detection", "trust",
    "included", "excluded", "effective_weights", "epoch_losses", "attack_details", "explanation",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def db_path() -> Path:
    return Path(config.DB_PATH)


@contextmanager
def connect():
    with _lock:
        db_path().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path(), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    with connect() as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript(SCHEMA)


def _encode(v: Any) -> Any:
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v)
    if isinstance(v, bool):
        return int(v)
    return v


def _decode_row(row: sqlite3.Row) -> dict:
    out = {}
    for k in row.keys():
        v = row[k]
        if k in JSON_COLUMNS and isinstance(v, str):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                pass
        out[k] = v
    return out


def insert(table: str, data: dict) -> int:
    data = {**data}
    if table != "experiment_results":
        data.setdefault("created_at", now())
    cols = ", ".join(data.keys())
    marks = ", ".join("?" for _ in data)
    with connect() as c:
        cur = c.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", [_encode(v) for v in data.values()])
        return int(cur.lastrowid)


def update(table: str, where: dict, data: dict) -> int:
    sets = ", ".join(f"{k} = ?" for k in data)
    cond = " AND ".join(f"{k} = ?" for k in where)
    with connect() as c:
        cur = c.execute(f"UPDATE {table} SET {sets} WHERE {cond}",
                        [_encode(v) for v in data.values()] + [_encode(v) for v in where.values()])
        return cur.rowcount


def query(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with connect() as c:
        return [_decode_row(r) for r in c.execute(sql, list(params)).fetchall()]


def query_one(sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with connect() as c:
        return c.execute(sql, list(params)).rowcount


def reset_experiments() -> None:
    """Delete all experiment data (clients and their on-chain registration are kept)."""
    with connect() as c:
        for t in ("blockchain_transactions", "trust_history", "security_analysis",
                  "model_updates", "training_rounds", "experiment_results"):
            c.execute(f"DELETE FROM {t}" + (" WHERE tx_type != 'register'" if t == "blockchain_transactions" else ""))
