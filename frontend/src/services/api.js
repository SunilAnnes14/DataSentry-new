import axios from "axios";

export const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api";

const http = axios.create({ baseURL: API_URL, timeout: 30000 });

export function errorMessage(err) {
  if (err?.response?.data?.detail) {
    const d = err.response.data.detail;
    if (Array.isArray(d)) return d.map((x) => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join("; ");
    return String(d);
  }
  if (err?.code === "ERR_NETWORK") return `Cannot reach the DataSentry API at ${API_URL}`;
  return err?.message || "Unknown error";
}

const get = (url, params) => http.get(url, { params }).then((r) => r.data);
const post = (url, body) => http.post(url, body).then((r) => r.data);
const put = (url, body) => http.put(url, body).then((r) => r.data);

export const api = {
  health: () => get("/health"),
  overview: () => get("/overview"),
  clients: () => get("/clients"),
  registerClient: (name) => post("/clients/register", { name }),
  settings: () => get("/settings"),
  saveSettings: (s) => put("/settings", s),
  resetSettings: () => post("/settings/reset"),
  startTraining: (mode, settings) => post("/training/start", { mode, settings }),
  stopTraining: () => post("/training/stop"),
  resetExperiments: () => post("/training/reset"),
  status: () => get("/training/status"),
  rounds: (experimentId) => get("/training/rounds", { experiment_id: experimentId || undefined }),
  experiments: () => get("/experiments"),
  securityAnalysis: (experimentId) => get("/security/analysis", { experiment_id: experimentId || undefined }),
  securityClients: (experimentId) => get("/security/clients", { experiment_id: experimentId || undefined }),
  verifyUpdate: (id) => get(`/updates/${id}/verify`),
  blockchainStatus: () => get("/blockchain/status"),
  blockchainConnect: () => post("/blockchain/connect"),
  contract: () => get("/blockchain/contract"),
  records: (params) => get("/blockchain/records", params),
  transaction: (hash) => get(`/blockchain/transactions/${hash}`),
  metrics: () => get("/model/metrics"),
};
