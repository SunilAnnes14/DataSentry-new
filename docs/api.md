# DataSentry REST API

Base URL: `http://127.0.0.1:8000/api` · Interactive docs: `http://127.0.0.1:8000/docs`

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | DB + blockchain status, training state |
| GET | `/overview` | Dashboard summary (organisations, totals, latest accuracy) |
| GET | `/clients` | Hospitals with wallets, data size, label counts, decision stats, live state |
| POST | `/clients/register` | `{name}` - (re)register a hospital wallet on-chain |
| GET / PUT | `/settings` | Read / validate + save experiment settings |
| POST | `/settings/reset` | Restore defaults |
| POST | `/training/start` | `{mode, settings?}` - mode ∈ `clean, poisoned, protected, centralized, custom, suite` |
| POST | `/training/stop` | Cooperative stop of the running job |
| POST | `/training/reset` | Delete experiment data (on-chain history is immutable) |
| GET | `/training/status` | Live job state: round, phase, per-client progress, logs, warnings |
| GET | `/training/rounds?experiment_id=` | Rounds with metrics, hashes, per-update decisions |
| GET | `/experiments`, `/experiments/{id}` | Experiment list / detail |
| POST | `/updates/submit` | Screen an external update vector (see below) |
| GET | `/updates/{id}/verify` | Recompute SHA-256 from artifact; compare with DB and chain |
| GET | `/security/analysis?experiment_id=&round=` | Feature scores, risk, decisions, explanations, alerts |
| GET | `/security/clients?experiment_id=` | Trust score, trust history, decision counts |
| GET | `/blockchain/status` | RPC, contract address, block height, on-chain counters |
| POST | `/blockchain/connect` | Reconnect (and register participants) |
| GET | `/blockchain/contract` | Address, chain id, public RPC URL and ABI (for ethers.js) |
| GET | `/blockchain/records?experiment_id=&tx_type=&status=` | Recorded transactions |
| GET | `/blockchain/transactions/{hash}` | DB record + live receipt + decoded events + contract state |
| GET | `/model/metrics` | Latest metrics per configuration with per-round curves |

Mode semantics (`/training/start`):

| mode | attack | defense |
|---|---|---|
| `clean` | off | off (scores recorded, audit only) |
| `poisoned` | on (from settings) | off |
| `protected` | on (from settings) | on |
| `custom` | settings `attack.enabled` | settings `defense_enabled` |
| `centralized` | - | - (pooled-data baseline) |
| `suite` | runs centralized → clean → poisoned → protected |

`POST /updates/submit` body:

```json
{ "client_name": "Hospital Alpha", "update": [4130 floats in DSv1 order], "num_samples": 42,
  "experiment_id": null, "round_number": null }
```

The update is scored against the other participants' stored updates from the
reference round (default: last round of the latest federated experiment).
This is screening only: the reference round is already finalised on-chain, so
the update is not aggregated and no transaction is sent.

Errors: `409` for state conflicts (job already running, nothing to stop),
`422` for validation errors, `503` when the blockchain is unreachable for an
operation that requires it.
