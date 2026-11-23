# Experiment results

Each folder holds `results.json` for the most recent completed run of that
configuration, written automatically by the backend (`core/experiment_service.py`).
Values are measured, never hand-edited. Re-generate with **Run full demo** in the
dashboard or `POST /api/training/start {"mode": "suite"}`.

| Folder | Configuration |
|---|---|
| `centralized/` | Pooled-data baseline, same network and epoch budget |
| `clean/` | Federated learning, no attack, defense off |
| `poisoned/` | Hospital Delta attacks, defense off |
| `protected/` | Hospital Delta attacks, DataSentry defense on |
