# Demo script (≈ 5 minutes)

Prerequisites: the three processes from the README are running (Hardhat node,
API, dashboard), and the seed is 42 (default) so the numbers below reproduce.
For a clean slate click **Reset** on the Overview page first.

| Step | Where | Action / what to say |
|---|---|---|
| 1 | **Overview** | Four hospitals, all registered on-chain (wallets 0x7099…, 0x3C44…, 0x90F7…, 0x15d3…). "Raw records never leave a node; only weight updates do." |
| 2 | **Settings** | Show the attack simulator: participant **Hospital Delta**, type **Label flipping + boosted update**, flip rate 100 %, strength ×3. Thresholds 0.40 / 0.70. |
| 3 | **Overview** | Click **Run full demo**. The network graph animates and the live log streams local training, update hashes and verdicts. The suite runs centralized → clean → poisoned → protected (~30 s including blockchain transactions). |
| 4 | **Federated Network** | Cards show per-client epoch progress; Delta's card turns red. The rounds table shows Delta marked *attacker (ground truth)* and **excluded** in the protected run. |
| 5 | **AI Security Center** | Three *Rejected* alerts for Delta (risk ≈ 0.99 / 0.95 / 0.99). Click an alert: per-step norm 2.8× median, cosine −0.77, validation loss +171 %. Trust: honest hospitals ≈ 93, Delta ≈ 8. Mention the IF switches from warm-up to hybrid in round 2. |
| 6 | **AI Security Center** | Switch experiment to *Poisoned FL (no defense)*: the same verdicts, but "aggregated anyway" - this is the audit-only baseline. |
| 7 | **Blockchain Explorer** | Filter type = *AI decision*. Open Delta's row: risk 9910 bps, decision REJECT, included = false, decoded `UpdateDecision` event. Click **Verify with ethers.js** - the browser re-reads the chain independently and every check turns green. |
| 8 | **Model Performance** | Centralized 96.5 % · Clean FL 93.9 % · Poisoned FL **15.8 %** · Protected FL **93.9 %**. Detection vs. ground truth 3/0/0 (TP/FP/FN). |
| 9 | (optional) **Swagger** | `http://127.0.0.1:8000/docs` → `GET /api/updates/{id}/verify` shows the artifact hash = DB hash = on-chain hash. |

Talking points on honesty:

* Pure label flipping (no boosting) only reaches SUSPICIOUS with these
  weights (risk ≈ 0.58–0.62) and is down-weighted, not rejected. On this easy
  dataset, it also barely moves accuracy (93.9 % undefended).
* Federated learning alone is not a privacy guarantee - updates can leak
  information; DataSentry does not add differential privacy or secure
  aggregation.
