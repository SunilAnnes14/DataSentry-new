"""Central configuration for the DataSentry backend.

Values can be overridden with environment variables (see ../.env.example).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env")

# ---------------------------------------------------------------- storage
DATA_DIR = Path(os.getenv("DATASENTRY_DATA_DIR", BACKEND_DIR / "data"))
DB_PATH = Path(os.getenv("DATASENTRY_DB_PATH", DATA_DIR / "datasentry.db"))
ARTIFACT_DIR = Path(os.getenv("DATASENTRY_ARTIFACT_DIR", DATA_DIR / "artifacts"))
EXPERIMENTS_DIR = Path(os.getenv("DATASENTRY_EXPERIMENTS_DIR", PROJECT_ROOT / "experiments"))

# ---------------------------------------------------------------- ML
SEED = int(os.getenv("DATASENTRY_SEED", "42"))

CLIENT_NAMES = ["Hospital Alpha", "Hospital Beta", "Hospital Gamma", "Hospital Delta"]

# ---------------------------------------------------------------- blockchain
RPC_URL = os.getenv("DATASENTRY_RPC_URL", "http://127.0.0.1:8545")
# RPC URL as reachable from the user's browser (differs from RPC_URL inside docker-compose)
PUBLIC_RPC_URL = os.getenv("DATASENTRY_PUBLIC_RPC_URL", RPC_URL)
CHAIN_ID = int(os.getenv("DATASENTRY_CHAIN_ID", "31337"))
BLOCKCHAIN_ENABLED = os.getenv("DATASENTRY_BLOCKCHAIN_ENABLED", "true").lower() == "true"
CONTRACT_ARTIFACT = Path(
    os.getenv(
        "DATASENTRY_CONTRACT_ARTIFACT",
        PROJECT_ROOT / "blockchain" / "artifacts" / "contracts" / "DataSentryRegistry.sol" / "DataSentryRegistry.json",
    )
)
IGNITION_DEPLOYMENT = PROJECT_ROOT / "blockchain" / "ignition" / "deployments" / f"chain-{CHAIN_ID}" / "deployed_addresses.json"
DEPLOYMENT_FILE = Path(os.getenv("DATASENTRY_DEPLOYMENT_FILE", DATA_DIR / "deployment.json"))
CONTRACT_ADDRESS = os.getenv("DATASENTRY_CONTRACT_ADDRESS", "")

# Private keys are read from the environment only. The defaults in
# .env.example are Hardhat's PUBLIC local development accounts (well known,
# never use them on a real network).
COORDINATOR_PRIVATE_KEY = os.getenv("DATASENTRY_COORDINATOR_KEY", "")
CLIENT_PRIVATE_KEYS = [os.getenv(f"DATASENTRY_CLIENT_KEY_{i}", "") for i in range(1, 5)]

# ---------------------------------------------------------------- API
CORS_ORIGINS = [o.strip() for o in os.getenv(
    "DATASENTRY_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if o.strip()]


def ensure_dirs() -> None:
    for d in (DATA_DIR, ARTIFACT_DIR, EXPERIMENTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
