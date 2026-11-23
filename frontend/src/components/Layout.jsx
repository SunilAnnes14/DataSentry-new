import { ArrowRight, Blocks, Gauge, LayoutDashboard, Menu, Network, RefreshCw, Settings, ShieldCheck, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../services/api";
import { useApp } from "./AppContext";
import { Button, IconButton, fmt } from "./ui";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/network", label: "Federated Network", icon: Network },
  { to: "/security", label: "AI Security Center", icon: ShieldCheck },
  { to: "/blockchain", label: "Blockchain Explorer", icon: Blocks },
  { to: "/performance", label: "Model Performance", icon: Gauge },
  { to: "/settings", label: "Settings", icon: Settings },
];

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="grid h-9 w-9 place-items-center rounded-xl bg-cyan-accent text-ink-950">
        <ShieldCheck size={20} strokeWidth={2.4} />
      </div>
      <span className="text-[22px] font-semibold tracking-tight text-text-primary">DataSentry</span>
    </div>
  );
}

function JobIndicator() {
  const { status, apiError } = useApp();
  let dot = "bg-good", text = "System ready";
  if (apiError) { dot = "bg-critical"; text = "API offline"; }
  else if (status) {
    const running = status.state === "running" || status.state === "stopping";
    if (running) {
      dot = "bg-cyan-accent pulse-dot";
      text = `${fmt.mode(status.experiment_id?.split("-")[0] || status.mode)} · round ${status.current_round}/${status.total_rounds} · ${status.phase || "starting"}`;
    } else if (status.state === "failed") { dot = "bg-critical"; text = "Last job failed"; }
    else text = `Training ${status.state}`;
  }
  return (
    <span className="inline-flex max-w-full items-center gap-2 truncate rounded-full border border-ink-600 bg-ink-850 px-3 py-1.5 text-xs text-text-secondary">
      <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} />
      <span className="truncate">{text}</span>
    </span>
  );
}

/** Illustration for the "First Steps" card: an open crate with a shield and two nodes. */
function FirstStepsArt() {
  return (
    <svg viewBox="0 0 140 90" className="h-24 w-auto" aria-hidden>
      <circle cx="36" cy="24" r="9" fill="#5ee2e6" opacity="0.9" />
      <circle cx="104" cy="20" r="7" fill="#5ee2e6" opacity="0.55" />
      <path d="M44 28 L60 40 M97 25 L82 38" stroke="#5ee2e6" strokeWidth="2" strokeDasharray="3 4" />
      <path d="M70 12 l16 6 v12 c0 10 -7 16 -16 20 c-9 -4 -16 -10 -16 -20 v-12 z" fill="#154a53" stroke="#5ee2e6" strokeWidth="2" />
      <path d="M63 30 l5 5 l9 -10" stroke="#c9fbfc" strokeWidth="2.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M30 48 h80 l-8 -8 h-64 z" fill="#2e3238" />
      <rect x="30" y="48" width="80" height="36" rx="3" fill="#a7adb5" />
      <rect x="30" y="48" width="80" height="8" fill="#6c727b" />
    </svg>
  );
}

function Sidebar({ onNavigate }) {
  const navigate = useNavigate();
  return (
    <div className="flex h-full flex-col">
      <nav className="flex flex-col gap-1">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} onClick={onNavigate}
            className={({ isActive }) => `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition ${
              isActive ? "bg-ink-700 text-text-primary" : "text-text-secondary hover:bg-ink-800 hover:text-text-primary"}`}>
            {({ isActive }) => (<>
              <Icon size={18} aria-hidden className={isActive ? "text-cyan-accent" : ""} /> {label}
            </>)}
          </NavLink>
        ))}
      </nav>
      <div className="mt-8 border-t border-ink-600 pt-6 text-center">
        <div className="flex justify-center"><FirstStepsArt /></div>
        <div className="mt-3 text-sm font-semibold text-text-primary">First Steps</div>
        <p className="mx-auto mt-1 max-w-[190px] text-xs leading-relaxed text-text-secondary">
          Configure the attacker and thresholds, then run the demo.
        </p>
        <Button variant="teal" className="mt-4 !px-5 !py-1.5 text-xs" onClick={() => { navigate("/settings"); onNavigate?.(); }}>
          Get started
        </Button>
      </div>
    </div>
  );
}

export default function Layout() {
  const [open, setOpen] = useState(false);
  const { apiError, status, refresh, runAction } = useApp();
  const [starting, setStarting] = useState(false);
  const running = status?.state === "running" || status?.state === "stopping";

  const runDemo = async () => {
    setStarting(true);
    try { await runAction(() => api.startTraining("suite"), "Started: full demo suite"); } catch { /* toast shown */ } finally { setStarting(false); }
  };

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-ink-600 bg-ink-900/90 backdrop-blur">
        <div className="mx-auto flex h-[72px] max-w-[1480px] items-center justify-between gap-3 px-4 lg:px-8">
          <div className="flex items-center gap-3">
            <button className="lg:hidden" aria-label="Open menu" onClick={() => setOpen(true)}><Menu size={22} /></button>
            <Brand />
          </div>
          <div className="hidden min-w-0 flex-1 justify-center md:flex"><JobIndicator /></div>
          <div className="flex items-center gap-3">
            <IconButton icon={RefreshCw} label="Refresh data" onClick={refresh} />
            <span className="hidden sm:block">
              <Button variant="outline" iconRight={ArrowRight} loading={starting} disabled={running} onClick={runDemo}
                className="!px-5 !py-2.5">Run full demo</Button>
            </span>
          </div>
        </div>
      </header>

      {open && (
        <div className="fixed inset-0 z-40 bg-ink-950/80 lg:hidden" onClick={() => setOpen(false)}>
          <aside className="h-full w-72 overflow-y-auto border-r border-ink-600 bg-ink-900 px-4 py-6" onClick={(e) => e.stopPropagation()}>
            <div className="mb-8 flex items-center justify-between"><Brand /><button aria-label="Close menu" onClick={() => setOpen(false)}><X size={20} /></button></div>
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}

      <div className="mx-auto flex w-full max-w-[1480px] flex-1">
        <aside className="sticky top-[72px] hidden h-[calc(100vh-72px)] w-64 shrink-0 overflow-y-auto border-r border-ink-600 px-4 py-6 lg:block">
          <Sidebar />
        </aside>
        <main className="min-w-0 flex-1 px-4 py-6 lg:px-8">
          <div className="mb-4 md:hidden"><JobIndicator /></div>
          {apiError && (
            <div className="mb-4 rounded-xl border border-critical/50 bg-critical/10 px-4 py-3 text-sm text-critical-text">
              {apiError}. Start it with <code className="mono">uvicorn main:app --port 8000</code> in <code className="mono">backend/</code>.
            </div>
          )}
          <Outlet />
          <footer className="mt-10 pb-2 text-center text-xs text-text-muted">
            DataSentry · federated learning with AI screening and an on-chain audit trail
          </footer>
        </main>
      </div>
    </div>
  );
}
