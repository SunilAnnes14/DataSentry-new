import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useFetch } from "../components/AppContext";
import ExperimentControls from "../components/ExperimentControls";
import { ChartTooltip, Empty, ErrorBox, Legend, Loading, Panel, fmt } from "../components/ui";
import { api } from "../services/api";

// fixed categorical order (validated adjacent pairs on the #121417 card surface)
const MODES = [
  { key: "centralized", label: "Centralized", color: "#c98500" },
  { key: "clean", label: "Clean FL", color: "#9085e9" },
  { key: "poisoned", label: "Poisoned FL", color: "#d95926" },
  { key: "protected", label: "Protected FL", color: "#199e9e" },
];
const METRICS = [["accuracy", "Accuracy"], ["precision", "Precision"], ["recall", "Recall"], ["f1", "F1 score"]];

export default function Performance() {
  const { data, error, loading, reload } = useFetch(() => api.metrics());
  const cmp = data?.comparison || {};
  const present = MODES.filter((m) => cmp[m.key]);

  const barData = METRICS.map(([k, label]) => Object.fromEntries([["metric", label],
    ...present.map((m) => [m.key, cmp[m.key].final_metrics[k]])]));
  const maxRounds = Math.max(0, ...present.map((m) => cmp[m.key].rounds.length));
  const roundData = (field) => Array.from({ length: maxRounds + 1 }, (_, i) => Object.fromEntries([["round", i],
    ...present.map((m) => [m.key, i === 0 ? (field === "accuracy" ? cmp[m.key].initial_metrics?.accuracy : cmp[m.key].initial_metrics?.loss)
      : cmp[m.key].rounds[i - 1]?.[field]])]));
  const legend = present.map((m) => ({ label: m.label, color: m.color }));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-xl font-semibold">Model Performance</h1>
          <p className="text-sm text-text-secondary">Measured on the held-out test set ({data?.dataset?.test_samples ?? "…"} samples). Positive class: malignant.</p>
        </div>
        <ExperimentControls />
      </div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Loading /> : !present.length ? <Empty>No completed experiments. Click “Run full demo” to measure all four configurations.</Empty> : (
        <>
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            {MODES.map((m) => (
              <div key={m.key} className="panel p-4">
                <div className="flex items-center gap-2 text-xs text-text-muted"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: m.color }} />{fmt.mode(m.key)}</div>
                <div className="mt-1 text-2xl font-semibold tabular">{fmt.pct(cmp[m.key]?.final_metrics.accuracy)}</div>
                <div className="text-xs text-text-secondary">{cmp[m.key] ? `F1 ${fmt.num(cmp[m.key].final_metrics.f1, 3)} · loss ${fmt.num(cmp[m.key].final_metrics.loss, 3)}` : "not run yet"}</div>
              </div>
            ))}
          </div>

          <Panel title="Final metrics comparison" subtitle="Latest completed run of each configuration" actions={<Legend items={legend} />}>
            <div className="h-72">
              <ResponsiveContainer>
                <BarChart data={barData} barGap={2} barCategoryGap="22%">
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="metric" tickLine={false} axisLine={false} />
                  <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} tickLine={false} axisLine={false} width={40} />
                  <Tooltip cursor={{ fill: "rgba(255,255,255,0.04)" }} content={<ChartTooltip valueFormat={(v) => fmt.pct(v, 1)} />} />
                  {present.map((m) => <Bar key={m.key} dataKey={m.key} name={m.label} fill={m.color} radius={[4, 4, 0, 0]} maxBarSize={34} stroke="#111316" strokeWidth={2} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Panel>

          <div className="grid gap-6 xl:grid-cols-2">
            {[["accuracy", "Test accuracy per round", (v) => fmt.pct(v, 1), [0, 1]], ["loss", "Test loss per round", (v) => fmt.num(v, 3), [0, "auto"]]].map(([field, title, f, domain]) => (
              <Panel key={field} title={title} subtitle="Round 0 = initial global model" actions={<Legend items={legend} />}>
                <div className="h-64">
                  <ResponsiveContainer>
                    <LineChart data={roundData(field)}>
                      <CartesianGrid vertical={false} />
                      <XAxis dataKey="round" tickLine={false} axisLine={false} tickFormatter={(r) => `R${r}`} />
                      <YAxis domain={domain} tickFormatter={field === "accuracy" ? (v) => `${Math.round(v * 100)}%` : undefined} tickLine={false} axisLine={false} width={40} />
                      <Tooltip content={<ChartTooltip valueFormat={f} labelFormat={(l) => `Round ${l}`} />} />
                      {present.map((m) => <Line key={m.key} dataKey={m.key} name={m.label} stroke={m.color} strokeWidth={2} dot={{ r: 4, stroke: "#111316", strokeWidth: 2 }} activeDot={{ r: 5 }} />)}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </Panel>
            ))}
          </div>

          <Panel title="Results table" subtitle="Exact measured values" bodyClass="p-0">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-left text-xs">
                <thead className="text-text-muted"><tr className="border-b border-ink-600">
                  {["Configuration", "Attack", "Defense", "Accuracy", "Precision", "Recall", "F1", "Loss", "Detection (TP/FP/FN)", "Experiment"].map((h) => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}
                </tr></thead>
                <tbody>
                  {present.map((m) => {
                    const c = cmp[m.key]; const fm = c.final_metrics; const d = c.detection;
                    return (
                      <tr key={m.key} className="border-b border-ink-700">
                        <td className="px-4 py-2"><span className="mr-2 inline-block h-2.5 w-2.5 rounded-sm" style={{ background: m.color }} />{fmt.mode(m.key)}</td>
                        <td className="px-4 py-2">{c.attack ? `${c.attack.attack_type} on ${c.attack.target_client.replace("Hospital ", "")} (×${c.attack.strength})` : "none"}</td>
                        <td className="px-4 py-2">{m.key === "centralized" ? "n/a" : c.defense_enabled ? "on" : "off"}</td>
                        {["accuracy", "precision", "recall", "f1"].map((k) => <td key={k} className="px-4 py-2 mono">{fmt.pct(fm[k], 2)}</td>)}
                        <td className="px-4 py-2 mono">{fmt.num(fm.loss, 4)}</td>
                        <td className="px-4 py-2 mono">{d ? `${d.true_positives}/${d.false_positives}/${d.false_negatives}` : "—"}</td>
                        <td className="px-4 py-2 mono text-text-muted">{c.experiment_id.slice(-6)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
