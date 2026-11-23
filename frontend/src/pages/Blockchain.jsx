import { CheckCircle2, ExternalLink, Link2, RefreshCw, ShieldCheck, Wallet, X, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useApp, useFetch } from "../components/AppContext";
import { Button, DecisionBadge, Empty, ErrorBox, Hash, Loading, Panel, TxStatus, fmt } from "../components/ui";
import { api, errorMessage } from "../services/api";
import { connectMetaMask, verifyTransactionInBrowser } from "../services/chain";

const TYPES = { register: "Register participant", start_round: "Start round", submit_update: "Submit update",
  record_decision: "AI decision", finalize_round: "Finalize round" };

function TxDrawer({ record, onClose }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [verify, setVerify] = useState(null);
  const [verifying, setVerifying] = useState(false);

  useEffect(() => {
    if (!record?.tx_hash) return;
    setDetail(null); setVerify(null); setError(null);
    api.transaction(record.tx_hash).then(setDetail).catch((e) => setError(errorMessage(e)));
  }, [record?.tx_hash]);

  const runVerify = async () => {
    setVerifying(true);
    try { setVerify(await verifyTransactionInBrowser(record)); }
    catch (e) { setVerify({ ok: false, message: e.message }); }
    finally { setVerifying(false); }
  };
  if (!record) return null;
  const chain = detail?.chain;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink-950/70" onClick={onClose}>
      <aside className="fade-in h-full w-full max-w-xl overflow-y-auto border-l border-ink-600 bg-ink-900 p-6" onClick={(e) => e.stopPropagation()}>
        <div className="mb-5 flex items-start justify-between gap-3">
          <div>
            <div className="text-xs text-text-muted">Transaction details</div>
            <h2 className="text-lg font-semibold">{TYPES[record.tx_type] || record.tx_type}</h2>
          </div>
          <button aria-label="Close" onClick={onClose} className="text-text-muted hover:text-text-primary"><X size={20} /></button>
        </div>
        <dl className="grid grid-cols-[130px_1fr] gap-x-3 gap-y-2.5 text-xs">
          <dt className="text-text-muted">Tx hash</dt><dd><Hash value={record.tx_hash} len={14} /></dd>
          <dt className="text-text-muted">Status (DB)</dt><dd><TxStatus status={record.status} /></dd>
          <dt className="text-text-muted">Block</dt><dd className="mono">{record.block_number ?? "—"}</dd>
          <dt className="text-text-muted">From</dt><dd><Hash value={record.from_address} len={10} /></dd>
          <dt className="text-text-muted">Contract</dt><dd><Hash value={record.contract_address} len={10} /></dd>
          <dt className="text-text-muted">Client</dt><dd>{record.client_name || "Coordinator"}</dd>
          <dt className="text-text-muted">Client wallet</dt><dd><Hash value={record.client_wallet} len={10} /></dd>
          <dt className="text-text-muted">Experiment</dt><dd className="mono">{record.experiment_id || "—"}</dd>
          <dt className="text-text-muted">Round</dt><dd className="mono">{record.round_number ?? "—"} {record.chain_round_id ? `(on-chain id ${record.chain_round_id})` : ""}</dd>
          <dt className="text-text-muted">{record.tx_type === "finalize_round" ? "Global model hash" : "Update hash"}</dt><dd><Hash value={record.update_hash} len={14} /></dd>
          {record.tx_type === "record_decision" && <>
            <dt className="text-text-muted">AI risk score</dt><dd className="mono">{fmt.num(record.risk_score_bps / 10000, 4)} ({record.risk_score_bps} bps)</dd>
            <dt className="text-text-muted">Decision</dt><dd><DecisionBadge decision={record.decision} small /></dd>
            <dt className="text-text-muted">Aggregated</dt><dd>{record.included ? "yes" : "no - excluded from FedAvg"}</dd>
          </>}
          {record.error && <><dt className="text-text-muted">Error</dt><dd className="text-critical-text">{record.error}</dd></>}
          <dt className="text-text-muted">Gas used</dt><dd className="mono">{record.gas_used ?? "—"}</dd>
        </dl>

        <h3 className="mt-6 mb-2 text-sm font-semibold">Live receipt from the chain (via backend)</h3>
        {error && <ErrorBox error={error} />}
        {!detail && !error && <Loading label="Fetching receipt…" />}
        {detail && detail.chain_error && <ErrorBox error={detail.chain_error} />}
        {chain && (
          <div className="rounded-lg border border-ink-600 bg-ink-850 p-3 text-xs">
            <div className="flex flex-wrap gap-x-5 gap-y-1">
              <span>Status: <b className={chain.status === "confirmed" ? "text-good-text" : "text-critical-text"}>{chain.status}</b></span>
              <span>Block <b className="mono">{chain.block_number}</b></span>
              <span>Confirmations <b className="mono">{chain.confirmations}</b></span>
              <span>{new Date(chain.timestamp * 1000).toLocaleString()}</span>
            </div>
            {chain.events.map((ev, i) => (
              <div key={i} className="mt-3">
                <div className="font-medium text-cyan-accent">event {ev.event}</div>
                <pre className="mono mt-1 overflow-x-auto whitespace-pre-wrap break-all text-[11px] text-text-secondary">{JSON.stringify(ev.args, null, 2)}</pre>
              </div>
            ))}
          </div>
        )}
        {detail?.on_chain_state && (
          <>
            <h3 className="mt-5 mb-2 text-sm font-semibold">Current contract state</h3>
            <pre className="mono overflow-x-auto whitespace-pre-wrap break-all rounded-lg border border-ink-600 bg-ink-850 p-3 text-[11px] text-text-secondary">{JSON.stringify(detail.on_chain_state, null, 2)}</pre>
          </>
        )}

        {record.status === "confirmed" && (
          <div className="mt-6 rounded-xl border border-cyan-accent/25 bg-teal-deep/25 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold">Independent verification</div>
                <div className="text-xs text-text-muted">Your browser reads the chain directly with ethers.js and compares it with the record.</div>
              </div>
              <Button icon={ShieldCheck} variant="teal" loading={verifying} onClick={runVerify}>Verify with ethers.js</Button>
            </div>
            {verify && (
              <div className="mt-3 text-xs">
                {verify.message && <div className="text-critical-text">{verify.message}</div>}
                {verify.checks?.map((c) => (
                  <div key={c.label} className="flex items-center gap-2 py-0.5">
                    {c.ok ? <CheckCircle2 size={14} className="text-good-text" /> : <XCircle size={14} className="text-critical-text" />}
                    <span className={c.ok ? "text-text-secondary" : "text-critical-text"}>{c.label}</span>
                  </div>
                ))}
                {verify.checks && <div className={`mt-2 font-semibold ${verify.ok ? "text-good-text" : "text-critical-text"}`}>{verify.ok ? "Record verified on-chain" : "Verification failed"}</div>}
              </div>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}

export default function BlockchainExplorer() {
  const { runAction, refresh } = useApp();
  const [params, setParams] = useSearchParams();
  const [filters, setFilters] = useState({ tx_type: "", experiment_id: "", status: "" });
  const status = useFetch(() => api.blockchainStatus());
  const exps = useFetch(() => api.experiments());
  const records = useFetch(() => api.records({ ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)), limit: 500 }),
    [filters.tx_type, filters.experiment_id, filters.status]);
  const [selected, setSelected] = useState(null);
  const [wallet, setWallet] = useState(null);

  useEffect(() => {
    const tx = params.get("tx");
    if (tx && records.data) {
      const r = records.data.find((x) => x.tx_hash === tx);
      if (r) setSelected(r);
    }
  }, [params, records.data]);

  const st = status.data;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-xl font-semibold">Blockchain Explorer</h1>
          <p className="text-sm text-text-secondary">Immutable audit trail: update hashes, AI risk scores and decisions. No data or weights on-chain.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button icon={Wallet} variant="ghost" onClick={async () => {
            try { setWallet(await connectMetaMask()); } catch (e) { runAction(() => Promise.reject(e)).catch(() => {}); }
          }}>{wallet ? `${wallet.address.slice(0, 6)}…${wallet.address.slice(-4)} · chain ${wallet.chainId}` : "Connect MetaMask"}</Button>
          <Button icon={RefreshCw} variant="ghost" loading={records.loading} onClick={() => { refresh(); status.reload(); }}>Refresh</Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="panel p-4">
          <div className="text-xs text-text-muted">Network</div>
          <div className={`mt-1 inline-flex items-center gap-2 font-semibold ${st?.connected ? "text-good-text" : "text-critical-text"}`}>
            <span className={`h-2 w-2 rounded-full ${st?.connected ? "bg-good" : "bg-critical"}`} />{st?.connected ? "Connected" : "Offline"}</div>
          <div className="mt-0.5 text-xs text-text-secondary mono">{st?.rpc_url} · chain {st?.chain_id}</div>
          {!st?.connected && st && <Button className="mt-2 !py-1 text-xs" variant="ghost" icon={Link2}
            onClick={() => runAction(api.blockchainConnect, "Blockchain reconnected").then(() => status.reload()).catch(() => {})}>Reconnect</Button>}
        </div>
        <div className="panel p-4"><div className="text-xs text-text-muted">DataSentryRegistry contract</div><div className="mt-1"><Hash value={st?.contract_address} len={12} /></div>
          <div className="mt-0.5 text-xs text-text-secondary">coordinator <Hash value={st?.coordinator} len={6} /></div></div>
        <div className="panel p-4"><div className="text-xs text-text-muted">Latest block</div><div className="mt-1 text-2xl font-semibold tabular">{st?.block_number ?? "—"}</div>
          <div className="text-xs text-text-secondary">signing: {st?.signing || "—"}</div></div>
        <div className="panel p-4"><div className="text-xs text-text-muted">On-chain totals</div><div className="mt-1 text-2xl font-semibold tabular">{st?.update_count ?? "—"} <span className="text-sm font-normal text-text-secondary">updates</span></div>
          <div className="text-xs text-text-secondary">{st?.round_count ?? "—"} rounds</div></div>
      </div>
      {st?.error && <ErrorBox error={st.error} />}

      <Panel title="Transactions" subtitle="Click a row for receipt, decoded events and independent verification" bodyClass="p-0"
        actions={<>
          <select aria-label="Type" value={filters.tx_type} onChange={(e) => setFilters({ ...filters, tx_type: e.target.value })} className="rounded-lg border border-ink-500 bg-ink-850 px-2 py-1.5 text-xs">
            <option value="">All types</option>{Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select aria-label="Experiment" value={filters.experiment_id} onChange={(e) => setFilters({ ...filters, experiment_id: e.target.value })} className="rounded-lg border border-ink-500 bg-ink-850 px-2 py-1.5 text-xs">
            <option value="">All experiments</option>{exps.data?.filter((e) => e.mode !== "centralized").map((e) => <option key={e.id} value={e.id}>{fmt.mode(e.mode)} · {e.id.slice(-6)}</option>)}
          </select>
          <select aria-label="Status" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })} className="rounded-lg border border-ink-500 bg-ink-850 px-2 py-1.5 text-xs">
            <option value="">Any status</option><option value="confirmed">Confirmed</option><option value="failed">Failed</option>
          </select>
        </>}>
        <ErrorBox error={records.error} onRetry={records.reload} />
        {records.loading && !records.data ? <Loading /> : !records.data?.length ? <div className="p-5"><Empty>No transactions recorded yet.</Empty></div> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] text-left text-xs">
              <thead className="text-text-muted"><tr className="border-b border-ink-600">
                {["Tx hash", "Block", "Type", "Client", "Wallet", "Round", "Update / model hash", "AI risk", "Decision", "Status", ""].map((h) => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}
              </tr></thead>
              <tbody>
                {records.data.map((r) => (
                  <tr key={r.id} onClick={() => { setSelected(r); setParams(r.tx_hash ? { tx: r.tx_hash } : {}); }}
                    className={`cursor-pointer border-b border-ink-700 hover:bg-ink-700/60 ${r.decision === "REJECT" ? "bg-critical/5" : ""}`}>
                    <td className="px-4 py-2"><Hash value={r.tx_hash} len={8} /></td>
                    <td className="px-4 py-2 mono">{r.block_number ?? "—"}</td>
                    <td className="px-4 py-2">{TYPES[r.tx_type] || r.tx_type}</td>
                    <td className="px-4 py-2">{r.client_name || <span className="text-text-muted">Coordinator</span>}</td>
                    <td className="px-4 py-2"><Hash value={r.client_wallet || r.from_address} len={6} /></td>
                    <td className="px-4 py-2 mono">{r.round_number ?? "—"}{r.experiment_mode ? <span className="ml-1 text-text-muted">{r.experiment_mode}</span> : null}</td>
                    <td className="px-4 py-2"><Hash value={r.update_hash} len={8} /></td>
                    <td className="px-4 py-2 mono">{r.risk_score_bps != null ? fmt.num(r.risk_score_bps / 10000, 3) : "—"}</td>
                    <td className="px-4 py-2">{r.decision ? <DecisionBadge decision={r.decision} small /> : "—"}</td>
                    <td className="px-4 py-2"><TxStatus status={r.status} /></td>
                    <td className="px-4 py-2 text-cyan-accent"><ExternalLink size={13} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <TxDrawer record={selected} onClose={() => { setSelected(null); setParams({}); }} />
    </div>
  );
}
