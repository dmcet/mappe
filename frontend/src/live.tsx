import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Status } from "./types";

/**
 * One EventSource for the whole app (/api/stream). It delivers the live status (jobs,
 * costs, what waits for you) once per second while something runs, plus the IDs of runs
 * and CVs that changed, so pages refetch only what they show.
 */

interface Live {
  status: Status | null;
  connected: boolean;
  /** Increases whenever the given run / CV (or any, for lists) changed. */
  version: (kind: "run" | "cv" | "any", id?: number) => number;
}

const LiveContext = createContext<Live>({
  status: null,
  connected: false,
  version: () => 0,
});

export function LiveProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [connected, setConnected] = useState(false);
  const versions = useRef(new Map<string, number>());
  const [, setTick] = useState(0);

  useEffect(() => {
    const source = new EventSource("/api/stream");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.addEventListener("status", (event) => {
      const data = JSON.parse((event as MessageEvent).data) as Status;
      setStatus(data);
      const changed = data.changed;
      if (changed && (changed.runs.length || changed.cvs.length)) {
        const bump = (key: string) => versions.current.set(key, (versions.current.get(key) ?? 0) + 1);
        changed.runs.forEach((id) => bump(`run:${id}`));
        changed.cvs.forEach((id) => bump(`cv:${id}`));
        bump("any");
        setTick((t) => t + 1);
      }
    });
    return () => source.close();
  }, []);

  const version = useCallback(
    (kind: "run" | "cv" | "any", id?: number) =>
      versions.current.get(kind === "any" ? "any" : `${kind}:${id}`) ?? 0,
    [],
  );

  return (
    <LiveContext.Provider value={{ status, connected, version }}>{children}</LiveContext.Provider>
  );
}

export function useLive(): Live {
  return useContext(LiveContext);
}

/** Load data, and load it again whenever ``version`` changes (or ``reload`` is called). */
export function useResource<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    load()
      .then((value) => {
        if (!cancelled) {
          setData(value);
          setError(null);
        }
      })
      .catch((err: Error) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, error, reload: () => setNonce((n) => n + 1), setData };
}
