import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../services/api";

const Ctx = createContext(null);

export function useApp() {
  return useContext(Ctx);
}

/**
 * Global state: training job status (polled from the backend), a data
 * "revision" counter that bumps whenever a job finishes or data is reset so
 * pages refetch, and toast notifications.
 */
export function AppProvider({ children }) {
  const [status, setStatus] = useState(null);
  const [apiError, setApiError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [toasts, setToasts] = useState([]);
  const prevState = useRef(null);
  const prevRound = useRef(null);

  const toast = useCallback((message, kind = "success") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, message, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);

  const refresh = useCallback(() => setRevision((r) => r + 1), []);

  const poll = useCallback(async () => {
    try {
      const s = await api.status();
      setStatus(s);
      setApiError(null);
      const key = `${s.experiment_id}:${s.current_round}:${s.phase}`;
      if (prevState.current === "running" && s.state !== "running" && s.state !== "stopping") {
        setRevision((r) => r + 1);
        if (s.state === "completed") toast("Training job completed - results updated from the backend");
        if (s.state === "failed") toast(`Training failed: ${s.error}`, "error");
        if (s.state === "stopped") toast("Training stopped", "info");
      } else if (s.state === "running" && prevRound.current && prevRound.current !== key && s.phase === "local_training") {
        setRevision((r) => r + 1); // a round just finished: refresh live pages
      }
      prevRound.current = key;
      prevState.current = s.state;
    } catch (e) {
      setApiError(errorMessage(e));
    }
  }, [toast]);

  useEffect(() => {
    poll();
    const running = status?.state === "running" || status?.state === "stopping";
    const id = setInterval(poll, running ? 800 : 3000);
    return () => clearInterval(id);
  }, [poll, status?.state]);

  const runAction = useCallback(async (fn, success) => {
    try {
      const res = await fn();
      if (success) toast(success);
      poll();
      return res;
    } catch (e) {
      toast(errorMessage(e), "error");
      throw e;
    }
  }, [poll, toast]);

  return (
    <Ctx.Provider value={{ status, apiError, revision, refresh, toast, runAction, poll }}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-[min(380px,calc(100vw-32px))] flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} role="status"
            className={`pointer-events-auto fade-in flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm shadow-2xl ${
              t.kind === "error" ? "border-critical/60 bg-ink-850 text-critical-text" :
              t.kind === "info" ? "border-ink-500 bg-ink-850 text-text-secondary" : "border-good/50 bg-ink-850 text-good-text"}`}>
            {t.kind === "error" ? <XCircle size={16} className="mt-0.5 shrink-0" /> : t.kind === "info" ?
              <Info size={16} className="mt-0.5 shrink-0" /> : <CheckCircle2 size={16} className="mt-0.5 shrink-0" />}
            <span className="flex-1 text-text-primary">{t.message}</span>
            <button aria-label="Dismiss" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}
              className="text-text-muted hover:text-text-primary"><X size={14} /></button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

/** Fetch helper bound to the global revision counter. */
export function useFetch(fn, deps = []) {
  const { revision } = useApp();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fn());
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { load(); }, [load, revision]);
  return { data, error, loading, reload: load };
}
