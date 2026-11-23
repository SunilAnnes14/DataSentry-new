import { FlaskConical, Play, RotateCcw, ShieldCheck, Skull, Square, Workflow } from "lucide-react";
import { useState } from "react";
import { api } from "../services/api";
import { useApp } from "./AppContext";
import { Button } from "./ui";

/** Real controls wired to /api/training/*. */
export default function ExperimentControls({ compact = false }) {
  const { status, runAction, refresh } = useApp();
  const [busy, setBusy] = useState(null);
  const running = status?.state === "running" || status?.state === "stopping";

  const act = async (key, fn, msg) => {
    setBusy(key);
    try { await runAction(fn, msg); } catch { /* toast already shown */ } finally { setBusy(null); }
  };
  const start = (mode) => act(mode, () => api.startTraining(mode), `Started: ${mode} experiment`);

  return (
    <div className={`flex flex-wrap gap-2 ${compact ? "" : ""}`}>
      <Button icon={Workflow} variant="teal" loading={busy === "suite"} disabled={running} onClick={() => start("suite")}
        title="Centralized baseline + clean + poisoned + protected">Run full demo</Button>
      <Button icon={FlaskConical} variant="ghost" loading={busy === "clean"} disabled={running} onClick={() => start("clean")}>Clean</Button>
      <Button icon={Skull} variant="ghost" loading={busy === "poisoned"} disabled={running} onClick={() => start("poisoned")}>Poisoned</Button>
      <Button icon={ShieldCheck} variant="ghost" loading={busy === "protected"} disabled={running} onClick={() => start("protected")}>Protected</Button>
      <Button icon={Play} loading={busy === "custom"} disabled={running} onClick={() => start("custom")}
        title="Uses the attack/defense switches from Settings">Start training</Button>
      <Button icon={Square} variant="danger" loading={busy === "stop"} disabled={!running} onClick={() => act("stop", api.stopTraining, "Stop requested")}>Stop</Button>
      <Button icon={RotateCcw} variant="ghost" loading={busy === "reset"} disabled={running}
        onClick={() => {
          if (!window.confirm("Delete all experiment results from the local database? (On-chain records are immutable and stay on the chain.)")) return;
          act("reset", async () => { const r = await api.resetExperiments(); refresh(); return r; }, "Experiment data reset");
        }}>Reset</Button>
    </div>
  );
}
