import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Status } from "./types";

/**
 * One EventSource for the whole app (/api/stream). It delivers the live status (jobs,
 * costs, what waits for you) once per second while something runs, plus the IDs of runs
 * and CVs that changed, so pages refetch only what they show.
 *
 * The connection can die without the browser reconnecting: clicking a download link (a
 * PDF, the ZIP, the .eml) or a shortcuts:// link aborts it in some browsers, and a sleeping
 * laptop can leave it half-open. So the server sends a message at least every
 * HEARTBEAT_S seconds, and the client opens a new connection when it hears nothing for
 * STALE_MS or the browser gives up. After every reconnect, and when the tab becomes visible
 * again, all pages refetch: changes made while disconnected are not lost.
 */

export const STALE_MS = 25_000; // the server sends at least every 10 s (live.py HEARTBEAT_S)
const RETRY_MS = [1_000, 2_000, 5_000, 10_000];

interface Live {
  status: Status | null;
  connected: boolean;
  /** Increases whenever the given run / CV (or any, for lists) changed. */
  version: (kind: "run" | "cv" | "any", id?: number) => number;
}

export const LiveContext = createContext<Live>({
  status: null,
  connected: false,
  version: () => 0,
});

export function LiveProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [connected, setConnected] = useState(false);
  const versions = useRef(new Map<string, number>());
  // Bumped after a reconnect or when the tab comes back: every version() changes.
  const epoch = useRef(0);
  const [, setTick] = useState(0);

  useEffect(() => {
    let source: EventSource | null = null;
    let lastMessage = Date.now();
    let opened = false;
    let failures = 0;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const refetchAll = () => {
      epoch.current += 1;
      setTick((t) => t + 1);
    };

    const connect = () => {
      clearTimeout(retry);
      source?.close();
      lastMessage = Date.now();
      const es = new EventSource("/api/stream");
      source = es;
      es.onopen = () => {
        setConnected(true);
        failures = 0;
        if (opened) refetchAll(); // reconnected: catch up on what was missed
        opened = true;
      };
      es.onerror = () => {
        setConnected(false);
        // CONNECTING: the browser retries by itself. CLOSED: it gave up, so we retry.
        if (es.readyState === EventSource.CLOSED && !closed) {
          retry = setTimeout(connect, RETRY_MS[Math.min(failures++, RETRY_MS.length - 1)]);
        }
      };
      es.addEventListener("status", (event) => {
        lastMessage = Date.now();
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
    };

    // A connection that looks open but delivers nothing is dead: replace it.
    const watchdog = setInterval(() => {
      if (Date.now() - lastMessage > STALE_MS) {
        setConnected(false);
        connect();
      }
    }, 5_000);

    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - lastMessage > STALE_MS || source?.readyState === EventSource.CLOSED) connect();
      else refetchAll();
    };
    document.addEventListener("visibilitychange", onVisible);

    connect();
    return () => {
      closed = true;
      clearInterval(watchdog);
      clearTimeout(retry);
      document.removeEventListener("visibilitychange", onVisible);
      source?.close();
    };
  }, []);

  const version = useCallback(
    (kind: "run" | "cv" | "any", id?: number) =>
      epoch.current * 1_000_000 + (versions.current.get(kind === "any" ? "any" : `${kind}:${id}`) ?? 0),
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
