import { RotateCcw, Save, ShieldOff, Skull } from "lucide-react";
import { useEffect, useState } from "react";
import { useApp, useFetch } from "../components/AppContext";
import { Button, ErrorBox, Loading, Panel } from "../components/ui";
import { api } from "../services/api";

const CLIENTS = ["Hospital Alpha", "Hospital Beta", "Hospital Gamma", "Hospital Delta"];
const ATTACKS = [
  ["label_flip_scaled", "Label flipping + boosted update"],
  ["label_flip", "Label flipping"],
  ["sign_flip", "Sign-reversed update"],
  ["scaling", "Scaled update"],
];

function Field({ label, hint, children }) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="text-text-secondary">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-text-muted">{hint}</span>}
    </label>
  );
}
const inputCls = "rounded-lg border border-ink-500 bg-ink-850 px-3 py-2 text-sm text-text-primary focus:border-cyan-accent focus:outline-none";

function Toggle({ checked, onChange, label }) {
  return (
    <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)} className="inline-flex items-center gap-3 text-sm">
      <span className={`relative h-6 w-11 rounded-full transition ${checked ? "bg-cyan-accent" : "bg-ink-500"}`}>
        <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${checked ? "left-[22px]" : "left-0.5"}`} />
      </span>
      {label}
    </button>
  );
}

export default function SettingsPage() {
  const { runAction, status } = useApp();
  const { data, error, loading, reload } = useFetch(() => api.settings());
  const [s, setS] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (data) setS(structuredClone(data)); }, [data]);
  const running = status?.state === "running";

  if (loading && !s) return <Loading />;
  if (!s) return <ErrorBox error={error} onRetry={reload} />;
  const set = (path, v) => setS((prev) => {
    const n = structuredClone(prev); const keys = path.split("."); let o = n;
    keys.slice(0, -1).forEach((k) => { o = o[k]; }); o[keys.at(-1)] = v; return n;
  });
  const save = async (next = s, msg = "Settings saved") => {
    setSaving(true);
    try { const r = await runAction(() => api.saveSettings(next), msg); setS(r); } catch { /* toast shown */ } finally { setSaving(false); }
  };
  const toggleAttack = (enabled) => { const n = structuredClone(s); n.attack.enabled = enabled; setS(n); save(n, enabled ? "Attack simulation ENABLED" : "Attack simulation disabled"); };
  const num = (path, parse = Number) => (e) => set(path, e.target.value === "" ? "" : parse(e.target.value));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-xl font-semibold">Settings</h1>
          <p className="text-sm text-text-secondary">Saved on the backend and applied to the next run. “Start training” uses these switches; preset buttons override attack/defense.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button icon={RotateCcw} variant="ghost" disabled={saving} onClick={() => runAction(api.resetSettings, "Defaults restored").then(setS).catch(() => {})}>Restore defaults</Button>
          <Button icon={Save} loading={saving} onClick={() => save()}>Save settings</Button>
        </div>
      </div>
      {running && <div className="rounded-lg border border-warning/40 bg-warning/10 px-4 py-2 text-xs text-warning">A job is running - changes apply to the next run.</div>}

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Attack simulator" subtitle="Malicious participant behaviour (never hard-coded into detection)"
          actions={s.attack.enabled
            ? <Button icon={ShieldOff} variant="ghost" onClick={() => toggleAttack(false)}>Disable attack</Button>
            : <Button icon={Skull} variant="danger" onClick={() => toggleAttack(true)}>Enable attack</Button>}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2"><Toggle checked={s.attack.enabled} onChange={(v) => set("attack.enabled", v)} label={s.attack.enabled ? "Attack enabled" : "Attack disabled"} /></div>
            <Field label="Attack participant">
              <select className={inputCls} value={s.attack.target_client} onChange={(e) => set("attack.target_client", e.target.value)}>
                {CLIENTS.map((c) => <option key={c}>{c}</option>)}
              </select>
            </Field>
            <Field label="Attack type">
              <select className={inputCls} value={s.attack.attack_type} onChange={(e) => set("attack.attack_type", e.target.value)}>
                {ATTACKS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Field>
            <Field label={`Label flip rate: ${Math.round(s.attack.flip_rate * 100)}%`} hint="Used by label-flipping attacks">
              <input type="range" min={0} max={1} step={0.05} value={s.attack.flip_rate} onChange={num("attack.flip_rate")} className="accent-cyan-400" />
            </Field>
            <Field label={`Attack strength: ×${s.attack.strength}`} hint="Update multiplier for boosted / sign-flip / scaling attacks">
              <input type="range" min={0.5} max={10} step={0.5} value={s.attack.strength} onChange={num("attack.strength")} className="accent-cyan-400" />
            </Field>
          </div>
        </Panel>

        <Panel title="AI security engine" subtitle="Risk = 0.35·norm + 0.30·cosine + 0.20·deviation + 0.15·validation">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2"><Toggle checked={s.defense_enabled} onChange={(v) => set("defense_enabled", v)} label={s.defense_enabled ? "Defense enforced" : "Defense disabled (audit only)"} /></div>
            <Field label="Suspicious threshold" hint="risk ≥ this → SUSPICIOUS"><input type="number" step="0.01" min="0.01" max="0.99" className={inputCls} value={s.security.accept_threshold} onChange={num("security.accept_threshold")} /></Field>
            <Field label="Reject threshold" hint="risk ≥ this → REJECT"><input type="number" step="0.01" min="0.02" max="1" className={inputCls} value={s.security.reject_threshold} onChange={num("security.reject_threshold")} /></Field>
            <Field label="Suspicious update policy">
              <select className={inputCls} value={s.security.suspicious_policy} onChange={(e) => set("security.suspicious_policy", e.target.value)}>
                <option value="downweight">Down-weight</option><option value="exclude">Exclude</option><option value="include">Include</option>
              </select>
            </Field>
            <Field label="Suspicious weight" hint="FedAvg multiplier when down-weighting"><input type="number" step="0.05" min="0" max="1" className={inputCls} value={s.security.suspicious_weight} onChange={num("security.suspicious_weight")} /></Field>
          </div>
        </Panel>

        <Panel title="Federated training">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Communication rounds"><input type="number" min="1" max="20" className={inputCls} value={s.rounds} onChange={num("rounds", parseInt)} /></Field>
            <Field label="Local epochs"><input type="number" min="1" max="10" className={inputCls} value={s.local_epochs} onChange={num("local_epochs", parseInt)} /></Field>
            <Field label="Batch size"><input type="number" min="4" max="256" className={inputCls} value={s.batch_size} onChange={num("batch_size", parseInt)} /></Field>
            <Field label="Learning rate"><input type="number" step="0.0001" min="0.0001" max="1" className={inputCls} value={s.learning_rate} onChange={num("learning_rate")} /></Field>
            <Field label="Random seed" hint="Fixed seed → reproducible demo"><input type="number" min="0" className={inputCls} value={s.seed} onChange={num("seed", parseInt)} /></Field>
            <Field label="Trust EMA α"><input type="number" step="0.05" min="0.05" max="1" className={inputCls} value={s.trust_alpha} onChange={num("trust_alpha")} /></Field>
          </div>
        </Panel>

        <Panel title="Data & infrastructure">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Data partitioning">
              <select className={inputCls} value={s.partition} onChange={(e) => set("partition", e.target.value)}>
                <option value="dirichlet">Non-IID (Dirichlet label skew)</option><option value="iid">IID</option>
              </select>
            </Field>
            <Field label="Dirichlet α" hint="Lower = more heterogeneous clients"><input type="number" step="0.1" min="0.1" className={inputCls} value={s.dirichlet_alpha} onChange={num("dirichlet_alpha")} /></Field>
            <div className="sm:col-span-2"><Toggle checked={s.blockchain_enabled} onChange={(v) => set("blockchain_enabled", v)} label="Record audit trail on-chain" /></div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
