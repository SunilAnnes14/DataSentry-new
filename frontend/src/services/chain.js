/**
 * Independent, browser-side verification of on-chain records with ethers.js.
 * The dashboard reads the chain directly (read-only JSON-RPC) and compares the
 * result with what the backend reports. No private keys ever reach the browser;
 * MetaMask is only used to show the connected wallet.
 */
import { BrowserProvider, Contract, JsonRpcProvider } from "ethers";
import { api } from "./api";

const DECISIONS = ["NONE", "ACCEPT", "SUSPICIOUS", "REJECT"];
let cached = null;

async function contractInfo() {
  if (!cached) cached = await api.contract();
  return cached;
}

export async function verifyTransactionInBrowser(record) {
  const info = await contractInfo();
  const provider = new JsonRpcProvider(info.rpc_url, info.chain_id, { staticNetwork: true });
  const receipt = await provider.getTransactionReceipt(record.tx_hash);
  if (!receipt) return { ok: false, message: "Receipt not found on chain" };
  const contract = new Contract(info.address, info.abi, provider);
  const out = {
    ok: receipt.status === 1,
    receiptStatus: receipt.status === 1 ? "success" : "reverted",
    blockNumber: receipt.blockNumber,
    to: receipt.to,
    contractMatches: receipt.to?.toLowerCase() === info.address?.toLowerCase(),
    checks: [],
  };
  if (record.chain_round_id && record.client_wallet && ["submit_update", "record_decision"].includes(record.tx_type)) {
    const u = await contract.getUpdate(record.chain_round_id, record.client_wallet);
    const onChain = {
      updateHash: u.updateHash,
      riskScoreBps: Number(u.riskScoreBps),
      decision: DECISIONS[Number(u.decision)],
      included: u.includedInAggregation,
    };
    out.onChain = onChain;
    if (record.update_hash) out.checks.push({ label: "Update hash", ok: onChain.updateHash === record.update_hash });
    if (record.tx_type === "record_decision") {
      out.checks.push({ label: "Risk score", ok: onChain.riskScoreBps === record.risk_score_bps });
      out.checks.push({ label: "Decision", ok: onChain.decision === record.decision });
      out.checks.push({ label: "Included flag", ok: Boolean(onChain.included) === Boolean(record.included) });
    }
  } else if (record.chain_round_id) {
    const r = await contract.getRound(record.chain_round_id);
    out.onChain = { status: ["NONE", "OPEN", "FINALIZED"][Number(r.status)], globalModelHash: r.globalModelHash,
      includedCount: Number(r.includedCount), submissions: Number(r.submissions) };
    if (record.tx_type === "finalize_round" && record.update_hash)
      out.checks.push({ label: "Global model hash", ok: r.globalModelHash === record.update_hash });
  }
  out.checks.unshift({ label: "Receipt status = 1", ok: receipt.status === 1 });
  out.checks.push({ label: "Sent to DataSentry contract", ok: out.contractMatches });
  out.ok = out.checks.every((c) => c.ok);
  return out;
}

export async function connectMetaMask() {
  if (!window.ethereum) throw new Error("MetaMask (window.ethereum) not detected in this browser");
  const provider = new BrowserProvider(window.ethereum);
  const accounts = await provider.send("eth_requestAccounts", []);
  const network = await provider.getNetwork();
  return { address: accounts[0], chainId: Number(network.chainId) };
}
