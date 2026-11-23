import { DECISION_COLOR } from "./ui";

/**
 * Star topology: four hospitals around the coordinator (aggregator + AI
 * security engine). Edge colour = latest security decision of that node;
 * flowing dashes while the node is actively training/submitting.
 */
export default function NetworkGraph({ organizations = [], live = {}, running }) {
  const W = 560, H = 340, cx = W / 2, cy = H / 2;
  const pos = [
    { x: 95, y: 70 }, { x: W - 95, y: 70 }, { x: 95, y: H - 70 }, { x: W - 95, y: H - 70 },
  ];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Federated network topology">
      <defs>
        <radialGradient id="core" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#5ee2e6" stopOpacity="0.22" />
          <stop offset="100%" stopColor="#5ee2e6" stopOpacity="0" />
        </radialGradient>
      </defs>
      {organizations.map((o, i) => {
        const p = pos[i % 4];
        const l = live[o.name] || {};
        const decision = l.decision || o.decision;
        const active = running && ["training", "submitted", "waiting"].includes(l.status);
        const color = active ? "#5ee2e6" : DECISION_COLOR[decision] || "#2e3238";
        return (
          <line key={`e-${o.name}`} x1={p.x} y1={p.y} x2={cx} y2={cy} stroke={color} strokeWidth={2}
            strokeOpacity={0.85} className={active ? "flow-line" : ""} />
        );
      })}
      <circle cx={cx} cy={cy} r={70} fill="url(#core)" />
      <g>
        <rect x={cx - 74} y={cy - 32} width={148} height={64} rx={14} fill="#0d0f12" stroke="#5ee2e6" strokeOpacity="0.6" />
        <text x={cx} y={cy - 8} textAnchor="middle" fill="#eef1f4" fontSize="13" fontWeight="600">Coordinator</text>
        <text x={cx} y={cy + 10} textAnchor="middle" fill="#a7adb5" fontSize="10.5">FedAvg + AI Security</text>
        <text x={cx} y={cy + 23} textAnchor="middle" fill="#5ee2e6" fontSize="10">on-chain audit</text>
      </g>
      {organizations.map((o, i) => {
        const p = pos[i % 4];
        const l = live[o.name] || {};
        const decision = l.decision || o.decision;
        const ring = DECISION_COLOR[decision] || "#2e3238";
        const statusText = running && l.status ? l.status : decision ? decision.toLowerCase() : "idle";
        return (
          <g key={o.name}>
            <rect x={p.x - 80} y={p.y - 30} width={160} height={60} rx={12} fill="#111316" stroke={ring} strokeWidth={1.5} />
            <text x={p.x} y={p.y - 8} textAnchor="middle" fill="#eef1f4" fontSize="12.5" fontWeight="600">{o.name}</text>
            <text x={p.x} y={p.y + 8} textAnchor="middle" fill="#a7adb5" fontSize="10.5">{o.num_samples ?? "—"} local samples</text>
            <text x={p.x} y={p.y + 22} textAnchor="middle" fill="#6c727b" fontSize="10">
              {statusText}{(l.risk ?? o.risk) != null ? ` · risk ${(l.risk ?? o.risk).toFixed(2)}` : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
