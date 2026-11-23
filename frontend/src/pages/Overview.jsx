import { Activity, Blocks, Building2, Gauge, Layers, ShieldAlert, Signal } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApp, useFetch } from "../components/AppContext";
import ExperimentControls from "../components/ExperimentControls";
import NetworkGraph from "../components/NetworkGraph";
import { ChartTooltip, DECISION_COLOR, Empty, ErrorBox, Legend, Loading, Panel, Stat, StatStrip, fmt } from "../components/ui";
import { api } from "../services/api";

const CONFIGS = [
  ["centralized", "Centralized"], ["clean", "Clean FL"], ["poisoned", "Poisoned FL"], ["protected", "Protected FL"],
];

function VerdictDonut({ totals }) {
  const parts = [
    { key: "ACCEPT", label: "Accepted", value: totals.accepted || 0 },
    { key: "SUSPICIOUS", label: "Suspicious", value: totals.suspicious || 0 },
    { key: "REJECT", label: "Rejected", value: totals.rejected || 0 },
  ];
  const total = parts.reduce((s, p) => s + p.value, 0);
  if (!total) return <Empty>No screened updates yet.</Empty>;
  return (
    <div className="flex flex-col gap-6">
      <div className="relative mx-auto h-44 w-44">
        <ResponsiveContainer>
          <PieChart>
            <Pie data={parts.filter((p) => p.value)} dataKey="value" nameKey="label" innerRadius="72%" outerRadius="100%"
              startAngle={90} endAngle={-270} paddingAngle={2} stroke="#111316" strokeWidth={2} cornerRadius={4}>
              {parts.filter((p) => p.value).map((p) => <Cell key={p.key} fill={DECISION_COLOR[p.key]} />)}
            </Pie>
            <Tooltip content={<ChartTooltip valueFormat={(v) => `${v} updates (${((v / total) * 100).toFixed(1)}%)`} labelFormat={() => "Security verdicts"} />} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
          <div><div className="text-xs text-text-muted">Total</div><div className="text-2xl font-semibold tabular">{total}</div></div>
        </div>
      </div>
      <ul className="flex flex-col gap-3 text-sm">
        {parts.map((p) => (
          <li key={p.key} className="flex items-center justify-between">
            <span className="flex items-center gap-2.5 text-text-secondary">
              <span className="h-4 w-1 rounded-full" style={{ background: DECISION_COLOR[p.key] }} />{p.label}
            </span>
            <span className="font-medium tabular text-text-primary">{p.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AccuracyBars({ comparison }) {
  const data = CONFIGS.filter(([k]) => comparison[k]).map(([k, label]) => ({ label, accuracy: comparison[k].final_metrics.accuracy }));
  if (!data.length) return <Empty>No completed experiments yet - click “Run full demo”.</Empty>;
  return (
    <div className="h-64">
      <ResponsiveContainer>
        <BarChart data={data} barCategoryGap="38%">
          <defs>
            <linearGradient id="acc-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#5ee2e6" />
              <stop offset="100%" stopColor="#1b6d78" />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="3 4" />
          <XAxis dataKey="label" tickLine={false} axisLine={false} />
          <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} tickLine={false} axisLine={false} width={40} />
          <Tooltip cursor={{ fill: "rgba(255,255,255,0.03)" }} content={<ChartTooltip valueFormat={(v) => fmt.pct(v, 2)} />} />
          <Bar dataKey="accuracy" name="Test accuracy" fill="url(#acc-fill)" radius={[6, 6, 6, 6]} maxBarSize={44}
            label={{ position: "top", fill: "#a7adb5", fontSize: 11, formatter: (v) => fmt.pct(v, 1) }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function Overview() {
  const { status } = useApp();
  const { data, error, loading, reload } = useFetch(() => api.overview());
  const metrics = useFetch(() => api.metrics());
  const running = status?.state === "running" || status?.state === "stopping";
  const protectedAcc = metrics.data?.comparison?.protected?.final_metrics?.accuracy;
  const poisonedAcc = metrics.data?.comparison?.poisoned?.final_metrics?.accuracy;

  return (
    <div className="flex flex-col gap-6">
      <div className="panel glass p-6">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="text-xs font-semibold tracking-[0.2em] text-cyan-accent">DATASENTRY CONSOLE</div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight lg:text-[30px]">Train Together. Share Nothing. Trust Everything.</h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
              Four hospitals train one diagnostic model without exchanging patient records. Every update is screened by
              the AI security engine before aggregation, and every verdict is anchored on-chain.
            </p>
          </div>
          <ExperimentControls />
        </div>
      </div>

      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Loading /> : data && (
        <>
          <StatStrip cols="md:grid-cols-2 xl:grid-cols-4">
            <Stat bare icon={Building2} label="Active organizations" value={data.active_organizations} hint="Registered on-chain" />
            <Stat bare icon={Layers} label="Current round" value={running ? `${status.current_round}/${status.total_rounds}` : "—"}
              hint={running ? fmt.mode(status.experiment_id?.split("-")[0]) : "No job running"} />
            <Stat bare icon={Activity} label="Model updates" value={data.totals.updates} hint={`Across ${data.totals.experiments} experiments`} />
            <Stat bare icon={ShieldAlert} accent="red" label="Threats detected" value={data.totals.threats} hint={`${data.totals.rejected} rejected`} />
          </StatStrip>
          <StatStrip cols="md:grid-cols-3">
            <Stat bare icon={Blocks} label="Blockchain transactions" value={data.totals.tx_confirmed}
              hint={data.totals.tx_failed ? `${data.totals.tx_failed} failed` : "All confirmed"} />
            <Stat bare icon={Gauge} accent="green" label="Global model accuracy" value={fmt.pct(data.latest_experiment?.final_metrics?.accuracy)}
              hint={data.latest_experiment ? fmt.mode(data.latest_experiment.mode) : "Run an experiment"} />
            <Stat bare icon={Signal} label="System status" value={data.blockchain.connected ? "Online" : "Degraded"}
              hint={data.blockchain.connected ? `Chain block #${data.blockchain.block_number}` : "Blockchain offline"}
              accent={data.blockchain.connected ? "green" : "red"} />
          </StatStrip>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
            <Panel title="Update verdicts" subtitle="All screened updates, all experiments">
              <VerdictDonut totals={data.totals} />
            </Panel>
            <Panel title="Test accuracy by configuration" subtitle="Latest completed run of each setup">
              {protectedAcc != null && poisonedAcc != null && (
                <div className="-mt-1 mb-4 flex flex-wrap items-baseline gap-2">
                  <span className="text-[26px] font-semibold tabular">{fmt.pct(protectedAcc, 1)}</span>
                  <span className="rounded-full bg-teal-deep px-2 py-0.5 text-[11px] font-medium text-teal-soft">
                    +{((protectedAcc - poisonedAcc) * 100).toFixed(1)} pts
                  </span>
                  <span className="text-xs text-text-muted">protected vs. poisoned without defense</span>
                </div>
              )}
              {metrics.loading && !metrics.data ? <Loading /> : <AccuracyBars comparison={metrics.data?.comparison || {}} />}
            </Panel>
          </div>

          <div className="grid gap-6 xl:grid-cols-5">
            <Panel className="xl:col-span-3" title="Federated network" subtitle="Live node status · edge colour = latest security verdict"
              actions={<Legend items={[{ label: "Accepted", color: DECISION_COLOR.ACCEPT }, { label: "Suspicious", color: DECISION_COLOR.SUSPICIOUS },
                { label: "Rejected", color: DECISION_COLOR.REJECT }, { label: "Training", color: "#5ee2e6" }]} />}>
              <NetworkGraph organizations={data.organizations} live={status?.clients || {}} running={running} />
            </Panel>
            <Panel className="xl:col-span-2" title="Live activity" subtitle="Streamed from the training job" bodyClass="px-0 pb-3 pt-2">
              <ol className="max-h-[380px] overflow-y-auto px-5 text-xs">
                {(status?.logs || []).slice().reverse().map((l, i) => (
                  <li key={i} className={`border-b border-ink-700 py-2 ${l.level === "warning" ? "text-warning" :
                    /REJECT|ATTACK/.test(l.msg) ? "text-critical-text" : "text-text-secondary"}`}>
                    <span className="mono mr-2 text-text-muted">{new Date(l.t).toLocaleTimeString()}</span>{l.msg}
                  </li>
                ))}
                {!status?.logs?.length && <li className="py-6 text-center text-text-muted">No activity yet - start an experiment.</li>}
              </ol>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
