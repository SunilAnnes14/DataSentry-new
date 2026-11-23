import { AlertOctagon, Info, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApp, useFetch } from "../components/AppContext";
import { Button, ChartTooltip, DECISION_COLOR, DecisionBadge, Empty, ErrorBox, Hash, Legend, Loading, Panel, fmt } from "../components/ui";
import { api } from "../services/api";

const CLIENT_COLORS = { "Hospital Alpha": "#199e9e", "Hospital Beta": "#d95926", "Hospital Gamma": "#9085e9", "Hospital Delta": "#c98500" };
const short = (n) => n?.replace("Hospital ", "");

function FeatureBreakdown({ a }) {
  const parts = [
    ["Norm anomaly", a.norm_anomaly, 0.35], ["Cosine disagreement", a.cosine_disagreement, 0.30],
    ["Weight deviation", a.deviation_score, 0.20], ["Validation impact", a.validation_impact, 0.15],
  ];
  return (
    <div className="flex flex-col gap-2">
      {parts.map(([label, v, w]) => (
        <div key={label} className="grid grid-cols-[150px_1fr_90px] items-center gap-3 text-xs">
          <span className="text-text-secondary">{label} <span className="text-text-muted">×{w}</span></span>
          <div className="h-2 rounded-full bg-ink-600"><div className="h-2 rounded-full bg-cyan-accent" style={{ width: `${v * 100}%` }} /></div>
          <span className="mono text-right text-text-primary">{fmt.num(v, 2)} → {fmt.num(v * w, 3)}</span>
        </div>
      ))}
      <div className="mt-1 flex items-center justify-between border-t border-ink-600 pt-2 text-xs">
        <span className="text-text-secondary">Weighted risk score</span><span className="mono text-sm font-semibold">{fmt.num(a.risk_score, 4)}</span>
      </div>
    </div>
  );
}

export default function SecurityCenter() {
  const { refresh, status } = useApp();
  const [expId, setExpId] = useState("");
  const exps = useFetch(() => api.experiments());
  const analysis = useFetch(() => api.securityAnalysis(expId), [expId]);
  const trust = useFetch(() => api.securityClients(expId), [expId]);
  const [selected, setSelected] = useState(null);
  const rows = analysis.data?.analyses || [];
  const thresholds = analysis.data?.thresholds || { accept_threshold: 0.4, reject_threshold: 0.7 };
  const maxRound = Math.max(0, ...rows.map((r) => r.round_number));
  const [roundSel, setRoundSel] = useState(0);
  const shownRound = roundSel || maxRound;
  const roundRows = rows.filter((r) => r.round_number === shownRound);
  const current = selected && rows.find((r) => r.id === selected) || rows.find((r) => r.decision === "REJECT") || rows[rows.length - 1];
  const enforced = analysis.data?.experiment?.config?.defense_enabled;

  const trustSeries = useMemo(() => {
    const clients = trust.data?.clients || [];
    const n = Math.max(0, ...clients.map((c) => c.trust_history.length));
    return Array.from({ length: n }, (_, i) => Object.fromEntries([["round", i],
      ...clients.map((c) => [c.client_name, c.trust_history[i]?.trust_score])]));
  }, [trust.data]);

  // end-of-line labels: clients whose final trust is within 6 points share one label
  const endLabels = useMemo(() => {
    const last = trustSeries[trustSeries.length - 1] || {};
    const vals = Object.keys(CLIENT_COLORS).filter((k) => last[k] != null).map((k) => [k, last[k]]).sort((a, b) => b[1] - a[1]);
    const groups = [];
    vals.forEach(([k, v]) => {
      const g = groups.find((x) => Math.abs(x.v - v) < 6);
      if (g) g.names.push(short(k)); else groups.push({ owner: k, v, names: [short(k)] });
    });
    return Object.fromEntries(groups.map((g) => [g.owner, `${g.names.join(" / ")} ${g.v.toFixed(0)}`]));
  }, [trustSeries]);

  const busy = analysis.loading || trust.loading;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-xl font-semibold">AI Security Center</h1>
          <p className="text-sm text-text-secondary">Hybrid MAD + cosine + Isolation Forest screening of every update before FedAvg.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select value={expId} onChange={(e) => { setExpId(e.target.value); setSelected(null); setRoundSel(0); }} aria-label="Experiment"
            className="rounded-lg border border-ink-500 bg-ink-850 px-2 py-2 text-xs">
            <option value="">Latest federated experiment</option>
            {exps.data?.filter((e) => e.mode !== "centralized").map((e) => <option key={e.id} value={e.id}>{fmt.mode(e.mode)} · {e.id.slice(-6)}</option>)}
          </select>
          <Button icon={RefreshCw} variant="ghost" loading={busy} onClick={() => { refresh(); exps.reload(); }}>Refresh analysis</Button>
        </div>
      </div>
      <ErrorBox error={analysis.error || trust.error} onRetry={() => { analysis.reload(); trust.reload(); }} />
      {analysis.loading && !analysis.data ? <Loading /> : !rows.length ? <Empty>No security analysis yet. Run a poisoned or protected experiment.</Empty> : (
        <>
          <div className="text-xs text-text-muted">
            Experiment <span className="mono text-text-secondary">{analysis.data.experiment.id}</span> · {fmt.mode(analysis.data.experiment.mode)} ·
            defense {enforced ? <span className="text-good-text">enforced</span> : <span className="text-warning">disabled (audit only)</span>}
            {analysis.data.experiment.detection && <> · detection vs. ground truth: TP {analysis.data.experiment.detection.true_positives}, FP {analysis.data.experiment.detection.false_positives}, FN {analysis.data.experiment.detection.false_negatives}</>}
            {status?.state === "running" && <span className="ml-2 text-cyan-accent">· live job running</span>}
          </div>

          {analysis.data.alerts.length > 0 && (
            <Panel title={`Attack alerts (${analysis.data.alerts.length})`} subtitle="Updates that did not pass screening">
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {analysis.data.alerts.map((a) => (
                  <button key={a.id} onClick={() => setSelected(a.id)}
                    className={`flex items-start gap-3 rounded-lg border p-3 text-left text-xs transition hover:bg-ink-700 ${a.decision === "REJECT" ? "border-critical/50 bg-critical/5" : "border-warning/40 bg-warning/5"}`}>
                    <AlertOctagon size={16} className={a.decision === "REJECT" ? "text-critical-text" : "text-warning"} />
                    <div className="min-w-0">
                      <div className="font-medium text-text-primary">{a.client_name} · round {a.round_number}</div>
                      <div className="text-text-secondary">risk {fmt.num(a.risk_score, 3)} · {a.included ? "aggregated (defense off)" : a.aggregation_weight > 0 ? `down-weighted ×${a.aggregation_weight}` : "excluded from FedAvg"}</div>
                    </div>
                    <span className="ml-auto"><DecisionBadge decision={a.decision} small /></span>
                  </button>
                ))}
              </div>
            </Panel>
          )}

          <div className="grid gap-6 xl:grid-cols-2">
            <Panel title="Risk score by client" subtitle={`Round ${shownRound} · dashed lines = accept / reject thresholds`}
              actions={<select value={shownRound} onChange={(e) => setRoundSel(Number(e.target.value))} aria-label="Round"
                className="rounded-lg border border-ink-500 bg-ink-850 px-2 py-1 text-xs">
                {Array.from({ length: maxRound }, (_, i) => <option key={i + 1} value={i + 1}>Round {i + 1}</option>)}
              </select>}>
              <Legend items={[{ label: "Accepted", color: DECISION_COLOR.ACCEPT }, { label: "Suspicious", color: DECISION_COLOR.SUSPICIOUS }, { label: "Rejected", color: DECISION_COLOR.REJECT }]} />
              <div className="mt-3 h-64">
                <ResponsiveContainer>
                  <BarChart data={roundRows.map((r) => ({ name: short(r.client_name), risk: r.risk_score, decision: r.decision, id: r.id }))} barCategoryGap="30%">
                    <CartesianGrid vertical={false} strokeDasharray="0" />
                    <XAxis dataKey="name" tickLine={false} axisLine={false} />
                    <YAxis domain={[0, 1]} tickLine={false} axisLine={false} width={32} />
                    <Tooltip cursor={{ fill: "rgba(255,255,255,0.04)" }} content={<ChartTooltip valueFormat={(v, p) => `${fmt.num(v, 3)} · ${p.payload.decision}`} />} />
                    <ReferenceLine y={thresholds.accept_threshold} stroke="#fab219" strokeDasharray="4 4" label={{ value: "suspicious", position: "insideTopRight", fill: "#a7adb5", fontSize: 10 }} />
                    <ReferenceLine y={thresholds.reject_threshold} stroke="#d03b3b" strokeDasharray="4 4" label={{ value: "reject", position: "insideTopRight", fill: "#a7adb5", fontSize: 10 }} />
                    <Bar dataKey="risk" name="Risk" radius={[4, 4, 0, 0]} maxBarSize={56} onClick={(d) => setSelected(d.id)} className="cursor-pointer">
                      {roundRows.map((r) => <Cell key={r.id} fill={DECISION_COLOR[r.decision]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel title="Participant trust score" subtitle="Trust = 100 × (1 − EMA(risk)); neutral start = 50. Not proof of intent.">
              <Legend items={Object.entries(CLIENT_COLORS).map(([k, c]) => ({ label: short(k), color: c }))} />
              <div className="mt-3 h-64">
                <ResponsiveContainer>
                  <LineChart data={trustSeries} margin={{ right: 16, top: 16 }}>
                    <CartesianGrid vertical={false} />
                    <XAxis dataKey="round" tickLine={false} axisLine={false} tickFormatter={(r) => (r === 0 ? "start" : `R${r}`)} />
                    <YAxis domain={[0, 100]} tickLine={false} axisLine={false} width={32} />
                    <Tooltip content={<ChartTooltip valueFormat={(v) => fmt.num(v, 1)} labelFormat={(l) => (l === 0 ? "Before round 1" : `After round ${l}`)} />} />
                    {Object.entries(CLIENT_COLORS).map(([k, c]) => (
                      <Line key={k} dataKey={k} name={short(k)} stroke={c} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "#111316" }} activeDot={{ r: 5 }}
                        label={({ x, y, index }) => index === trustSeries.length - 1 && endLabels[k] ? (
                          <text x={x - 8} y={y - 10} textAnchor="end" fill="#a7adb5" fontSize={11}>{endLabels[k]}</text>) : null} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          </div>

          {current && (
            <Panel title={`Detection explanation · ${current.client_name} · round ${current.round_number}`}
              subtitle={`Detector mode: ${current.detector_mode}`} actions={<DecisionBadge decision={current.decision} />}>
              <div className="grid gap-6 lg:grid-cols-2">
                <div>
                  <ul className="flex flex-col gap-2 text-sm">
                    {current.explanation?.map((e, i) => (
                      <li key={i} className="flex gap-2 text-text-secondary"><Info size={14} className="mt-0.5 shrink-0 text-cyan-accent" />{e}</li>
                    ))}
                  </ul>
                  <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3">
                    {[["L2 norm", fmt.num(current.l2_norm, 4)], ["Norm / step", fmt.num(current.norm_per_step, 5)], ["Robust z", fmt.num(current.norm_z, 2)],
                      ["Cosine similarity", fmt.num(current.cosine_similarity, 3)], ["Weight deviation", fmt.num(current.weight_deviation, 5)],
                      ["Isolation Forest", current.isolation_score == null ? "warm-up" : fmt.num(current.isolation_score, 3)],
                      ["Val. loss after", fmt.num(current.validation_loss, 4)], ["Median candidate", fmt.num(current.validation_loss_baseline, 4)],
                      ["Aggregation weight", fmt.num(current.aggregation_weight, 2)]].map(([k, v]) => (
                      <div key={k}><dt className="text-text-muted">{k}</dt><dd className="mono text-text-primary">{v}</dd></div>
                    ))}
                  </dl>
                  <div className="mt-4 flex flex-wrap items-center gap-3 text-xs">
                    <span className="text-text-muted">Update</span><Hash value={current.update_hash} />
                    {current.decision_tx && <Link className="text-cyan-accent hover:underline" to={`/blockchain?tx=${current.decision_tx}`}>View on-chain decision →</Link>}
                  </div>
                </div>
                <FeatureBreakdown a={current} />
              </div>
            </Panel>
          )}

          <Panel title="Update analysis log" subtitle="Click a row to inspect its explanation" bodyClass="p-0">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-left text-xs">
                <thead className="text-text-muted"><tr className="border-b border-ink-600">
                  {["Round", "Client", "L2 norm", "Cosine", "Deviation", "Val. impact", "IF score", "Risk", "Decision", "Aggregated"].map((h) => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}
                </tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} onClick={() => setSelected(r.id)}
                      className={`cursor-pointer border-b border-ink-700 hover:bg-ink-700/60 ${current?.id === r.id ? "bg-ink-700/70" : ""}`}>
                      <td className="px-4 py-2 mono">{r.round_number}</td>
                      <td className="px-4 py-2">{r.client_name}</td>
                      <td className="px-4 py-2 mono">{fmt.num(r.l2_norm, 3)}</td>
                      <td className="px-4 py-2 mono">{fmt.num(r.cosine_similarity, 2)}</td>
                      <td className="px-4 py-2 mono">{fmt.num(r.deviation_score, 2)}</td>
                      <td className="px-4 py-2 mono">{fmt.num(r.validation_impact, 2)}</td>
                      <td className="px-4 py-2 mono">{r.isolation_score == null ? "—" : fmt.num(r.isolation_score, 2)}</td>
                      <td className="px-4 py-2 mono font-semibold">{fmt.num(r.risk_score, 3)}</td>
                      <td className="px-4 py-2"><DecisionBadge decision={r.decision} small /></td>
                      <td className="px-4 py-2">{r.included ? "yes" : <span className="text-critical-text">no</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Participant history" subtitle="Counts in the selected experiment · all-time totals across experiments">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {trust.data?.clients.map((c) => (
                <div key={c.client_name} className="rounded-xl border border-ink-600 bg-ink-850/60 p-4">
                  <div className="flex items-center justify-between"><span className="font-medium">{c.client_name}</span>
                    <span className={`mono text-lg font-semibold ${c.trust_score < 40 ? "text-critical-text" : c.trust_score < 60 ? "text-warning" : "text-good-text"}`}>{fmt.num(c.trust_score, 1)}</span></div>
                  <div className="mt-1 text-[11px] text-text-muted">current trust score</div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                    <div><div className="text-text-muted">Accepted</div><div className="mono text-good-text">{c.accepted}</div></div>
                    <div><div className="text-text-muted">Suspicious</div><div className="mono text-warning">{c.suspicious}</div></div>
                    <div><div className="text-text-muted">Rejected</div><div className="mono text-critical-text">{c.rejected}</div></div>
                  </div>
                  <div className="mt-2 text-[11px] text-text-muted">All-time: {c.all_time.updates} updates · {c.all_time.rejected} rejected · {c.all_time.suspicious} suspicious</div>
                </div>
              ))}
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
