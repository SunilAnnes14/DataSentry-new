import { AlertTriangle, CheckCircle2, Copy, Loader2, ShieldX, XCircle } from "lucide-react";
import { useState } from "react";

export function Panel({ title, subtitle, actions, children, className = "", bodyClass = "" }) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold text-text-primary">{title}</h2>
            {subtitle && <p className="mt-1 text-xs text-text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={`p-5 ${bodyClass}`}>{children}</div>
    </section>
  );
}

/** Metric card: label + round icon badge on top, big value, muted hint. */
export function Stat({ label, value, hint, icon: Icon, accent = "cyan", bare = false }) {
  const tone = accent === "red" ? "text-critical-text" : accent === "green" ? "text-good-text" : "text-cyan-accent";
  return (
    <div className={`${bare ? "" : "panel"} flex flex-col gap-3 p-5`}>
      <div className="flex items-start justify-between gap-3">
        <span className="text-sm text-text-secondary">{label}</span>
        {Icon && (
          <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-full border border-ink-500 bg-ink-700 ${tone}`}>
            <Icon size={16} aria-hidden />
          </span>
        )}
      </div>
      <div>
        <div className="truncate text-[26px] leading-tight font-semibold tabular text-text-primary">{value}</div>
        {hint && <div className="mt-1 truncate text-xs text-text-muted">{hint}</div>}
      </div>
    </div>
  );
}

/** Several stats joined in one card with vertical dividers. */
export function StatStrip({ children, cols = "md:grid-cols-3" }) {
  return (
    <div className={`panel grid grid-cols-1 divide-y divide-ink-600 overflow-hidden md:divide-x md:divide-y-0 ${cols}`}>
      {children}
    </div>
  );
}

const DECISION_STYLE = {
  ACCEPT: { cls: "bg-good/15 text-good-text border-good/40", icon: CheckCircle2, label: "Accepted" },
  SUSPICIOUS: { cls: "bg-warning/15 text-warning border-warning/40", icon: AlertTriangle, label: "Suspicious" },
  REJECT: { cls: "bg-critical/15 text-critical-text border-critical/50", icon: ShieldX, label: "Rejected" },
};

export const DECISION_COLOR = { ACCEPT: "#0ca30c", SUSPICIOUS: "#fab219", REJECT: "#d03b3b" };

export function DecisionBadge({ decision, small }) {
  const s = DECISION_STYLE[decision];
  if (!s) return <span className="text-xs text-text-muted">—</span>;
  const Icon = s.icon;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 ${small ? "py-0 text-[11px]" : "py-0.5 text-xs"} font-medium ${s.cls}`}>
      <Icon size={small ? 11 : 13} aria-hidden /> {s.label}
    </span>
  );
}

export function TxStatus({ status }) {
  if (status === "confirmed")
    return <span className="inline-flex items-center gap-1 text-xs text-good-text"><CheckCircle2 size={13} aria-hidden /> Confirmed</span>;
  return <span className="inline-flex items-center gap-1 text-xs text-critical-text"><XCircle size={13} aria-hidden /> Failed</span>;
}

export function Button({ children, onClick, variant = "primary", loading, disabled, icon: Icon, iconRight: IconRight, className = "", type = "button", title }) {
  const styles = {
    primary: "bg-cyan-accent text-ink-950 hover:bg-teal-soft font-semibold",
    teal: "bg-teal-deep text-teal-soft hover:bg-[#1b5c66] font-semibold",
    outline: "border border-ink-500 text-text-primary hover:border-cyan-accent/60 font-semibold",
    ghost: "border border-ink-600 bg-ink-850 text-text-secondary hover:border-ink-500 hover:text-text-primary",
    danger: "border border-critical/50 text-critical-text hover:bg-critical/15",
  };
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-full px-4 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-45 ${styles[variant] || styles.primary} ${className}`}>
      {loading ? <Loader2 size={15} className="animate-spin" aria-hidden /> : Icon && <Icon size={15} aria-hidden />}
      {children}
      {IconRight && !loading && <IconRight size={15} aria-hidden />}
    </button>
  );
}

export function IconButton({ icon: Icon, onClick, label, loading }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick}
      className="grid h-10 w-10 place-items-center rounded-full border border-ink-500 text-text-primary transition hover:border-cyan-accent/60 hover:text-cyan-accent">
      {loading ? <Loader2 size={17} className="animate-spin" /> : <Icon size={17} />}
    </button>
  );
}

export function Hash({ value, len = 10 }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span className="text-text-muted">—</span>;
  const short = value.length > len * 2 ? `${value.slice(0, len)}…${value.slice(-6)}` : value;
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap mono text-xs text-text-secondary" title={value}>
      {short}
      <button type="button" aria-label="Copy" className="text-text-muted hover:text-cyan-accent"
        onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1000); }}>
        {copied ? <CheckCircle2 size={12} /> : <Copy size={12} />}
      </button>
    </span>
  );
}

export function Empty({ children }) {
  return <div className="rounded-xl border border-dashed border-ink-500 p-6 text-center text-sm text-text-muted">{children}</div>;
}

export function Loading({ label = "Loading…" }) {
  return <div className="flex items-center gap-2 p-6 text-sm text-text-muted"><Loader2 size={16} className="animate-spin" /> {label}</div>;
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-critical/50 bg-critical/10 px-4 py-3 text-sm text-critical-text">
      <span className="inline-flex items-center gap-2"><XCircle size={15} /> {error}</span>
      {onRetry && <Button variant="ghost" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function Progress({ value, tone = "cyan" }) {
  const c = tone === "red" ? "bg-critical" : tone === "green" ? "bg-good" : tone === "yellow" ? "bg-warning" : "bg-cyan-accent";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-600">
      <div className={`h-full rounded-full ${c} transition-all duration-500`} style={{ width: `${Math.max(0, Math.min(1, value || 0)) * 100}%` }} />
    </div>
  );
}

export const fmt = {
  pct: (v, d = 1) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`),
  num: (v, d = 3) => (v == null || Number.isNaN(v) ? "—" : Number(v).toFixed(d)),
  time: (iso) => (iso ? new Date(iso).toLocaleString() : "—"),
  mode: (m) => ({ centralized: "Centralized baseline", clean: "Clean FL", poisoned: "Poisoned FL (no defense)",
    protected: "Protected FL (DataSentry)", custom: "Custom run", suite: "Full demo suite" }[m] || m),
};

export function ChartTooltip({ active, payload, label, valueFormat = (v) => fmt.num(v, 3), labelFormat = (l) => l }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-ink-500 bg-ink-850/95 px-3 py-2 text-xs shadow-xl">
      <div className="mb-1 font-medium text-text-primary">{labelFormat(label)}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center justify-between gap-4">
          <span className="inline-flex items-center gap-1.5 text-text-secondary">
            <span className="h-2 w-2 rounded-full" style={{ background: p.color || p.payload?.fill }} />{p.name}
          </span>
          <span className="mono text-text-primary">{valueFormat(p.value, p)}</span>
        </div>
      ))}
    </div>
  );
}

/** Legend with round dots, as used across the dashboard. */
export function Legend({ items }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: i.color }} />{i.label}
        </span>
      ))}
    </div>
  );
}

export const SURFACE = "#111316";
