import { Building2, Wallet } from "lucide-react";
import { useState } from "react";
import { useApp, useFetch } from "../components/AppContext";
import ExperimentControls from "../components/ExperimentControls";
import { Button, DecisionBadge, Empty, ErrorBox, Hash, Loading, Panel, Progress, fmt } from "../components/ui";
import { api } from "../services/api";

function OrgCard({ c, live, running, onRegister }) {
  const st = live || {};
  const statusLabel = running ? st.status || "idle" : "idle";
  const tone = st.decision === "REJECT" ? "red" : st.decision === "SUSPICIOUS" ? "yellow" : st.decision === "ACCEPT" ? "green" : "cyan";
  const total = (c.label_counts?.[0] ?? 0) + (c.label_counts?.[1] ?? 0);
  return (
    <div className="panel flex flex-col gap-4 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-cyan-accent/10 p-2 text-cyan-accent"><Building2 size={18} /></div>
          <div>
            <div className="font-semibold">{c.name}</div>
            <div className="text-xs text-text-muted">{c.num_samples} private samples · never leave the node</div>
          </div>
        </div>
        {st.decision ? <DecisionBadge decision={st.decision} /> : <span className="text-xs text-text-muted capitalize">{statusLabel}</span>}
      </div>
      <div>
        <div className="mb-1 flex justify-between text-xs text-text-secondary">
          <span className="capitalize">Local training: {statusLabel}</span>
          <span className="mono">{running && st.epochs ? `epoch ${st.epoch}/${st.epochs}` : ""}</span>
        </div>
        <Progress value={running ? st.progress : 0} tone={tone} />
      </div>
      <div>
        <div className="mb-1 text-xs text-text-muted">Label distribution (non-IID)</div>
        <div className="flex h-2 overflow-hidden rounded-full bg-ink-600" aria-label="label distribution">
          <div className="bg-series-2" style={{ width: `${(c.label_counts?.[0] / total) * 100 || 0}%` }} title="malignant" />
          <div className="ml-[2px] flex-1 bg-series-1" title="benign" />
        </div>
        <div className="mt-1 flex justify-between text-[11px] text-text-secondary">
          <span>malignant {c.label_counts?.[0]}</span><span>benign {c.label_counts?.[1]}</span>
        </div>
      </div>
      <dl className="grid grid-cols-3 gap-2 text-center">
        {[["Accepted", c.stats.accepted, "text-good-text"], ["Suspicious", c.stats.suspicious, "text-warning"], ["Rejected", c.stats.rejected, "text-critical-text"]].map(([l, v, cls]) => (
          <div key={l} className="rounded-lg bg-ink-700/60 py-2"><dt className="text-[11px] text-text-muted">{l}</dt><dd className={`text-lg font-semibold tabular ${cls}`}>{v || 0}</dd></div>
        ))}
      </dl>
      <div className="flex flex-col gap-1 text-xs">
        <div className="flex items-center justify-between gap-2"><span className="inline-flex items-center gap-1 text-text-muted"><Wallet size={12} /> Wallet</span><Hash value={c.wallet_address} len={8} /></div>
        <div className="flex items-center justify-between gap-2"><span className="text-text-muted">Last update</span><Hash value={st.update_hash} len={8} /></div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-text-muted">On-chain registration</span>
          {c.registered_on_chain ? <Hash value={c.registration_tx} len={8} /> :
            <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={onRegister}>Register</Button>}
        </div>
      </div>
    </div>
  );
}

export default function NetworkPage() {
  const { status, runAction, refresh } = useApp();
  const running = status?.state === "running" || status?.state === "stopping";
  const clients = useFetch(() => api.clients());
  const [expId, setExpId] = useState("");
  const exps = useFetch(() => api.experiments());
  const rounds = useFetch(() => api.rounds(expId), [expId]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-xl font-semibold">Federated Network</h1>
          <p className="text-sm text-text-secondary">Each hospital trains locally and only submits a model update (weight delta).</p>
        </div>
        <ExperimentControls />
      </div>
      <ErrorBox error={clients.error} onRetry={clients.reload} />
      {clients.loading && !clients.data ? <Loading /> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {clients.data?.map((c) => (
            <OrgCard key={c.name} c={c} live={status?.clients?.[c.name]} running={running}
              onRegister={() => runAction(() => api.registerClient(c.name), `${c.name} registered on-chain`).then(refresh).catch(() => {})} />
          ))}
        </div>
      )}

      <Panel title="Communication rounds" subtitle="Per-round aggregation outcome from the database"
        actions={
          <select value={expId} onChange={(e) => setExpId(e.target.value)} aria-label="Experiment"
            className="rounded-lg border border-ink-500 bg-ink-850 px-2 py-1.5 text-xs">
            <option value="">Latest experiment</option>
            {exps.data?.map((e) => <option key={e.id} value={e.id}>{fmt.mode(e.mode)} · {e.id.slice(-6)} · {e.status}</option>)}
          </select>}>
        {rounds.loading && !rounds.data ? <Loading /> : !rounds.data?.rounds?.length ? <Empty>No rounds recorded yet.</Empty> : (
          <div className="flex flex-col gap-4">
            <div className="text-xs text-text-muted">Experiment <span className="mono text-text-secondary">{rounds.data.experiment.id}</span> · {fmt.mode(rounds.data.experiment.mode)} · blockchain: {rounds.data.experiment.blockchain_status || "n/a"}</div>
            {rounds.data.rounds.map((r) => (
              <div key={r.round_number} className="rounded-xl border border-ink-600 bg-ink-850/60 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="font-medium">Round {r.round_number}</div>
                  <div className="flex flex-wrap items-center gap-4 text-xs text-text-secondary">
                    <span>Test accuracy <b className="mono text-text-primary">{fmt.pct(r.accuracy)}</b></span>
                    <span>Loss <b className="mono text-text-primary">{fmt.num(r.loss)}</b></span>
                    <span className="inline-flex items-center gap-1">Global model <Hash value={r.global_hash} len={8} /></span>
                  </div>
                </div>
                {r.updates.length > 0 && (
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full min-w-[640px] text-left text-xs">
                      <thead className="text-text-muted"><tr><th className="py-1.5">Client</th><th>Update hash</th><th>Samples</th><th>Risk</th><th>Decision</th><th>Aggregated</th></tr></thead>
                      <tbody>
                        {r.updates.map((u) => (
                          <tr key={u.id} className="border-t border-ink-700">
                            <td className="py-1.5">{u.client_name}{u.is_malicious ? <span className="ml-2 rounded bg-critical/20 px-1.5 text-[10px] text-critical-text">attacker (ground truth)</span> : null}</td>
                            <td><Hash value={u.update_hash} len={8} /></td>
                            <td className="mono">{u.num_samples}</td>
                            <td className="mono">{fmt.num(u.risk_score)}</td>
                            <td><DecisionBadge decision={u.decision} small /></td>
                            <td className={u.included ? "text-text-secondary" : "font-medium text-critical-text"}>
                              {u.included ? `yes (weight ${fmt.num(u.aggregation_weight, 2)})` : "excluded"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
