"use client";

import { useCallback, useEffect, useReducer, useRef, useState, type Dispatch } from "react";
import { getAuthToken, type Run } from "./api";
// import { refreshSession } from "./api"; // cookie refresh, replaced by Clerk
import { initialRunState, isFinishedRun, runReducer, type RunState, type RunAction, type StreamMessage } from "./runState";

const MAX_ATTEMPTS = 6;

export { isFinishedRun };

/**
 * Subscribe to a run's SSE stream. Reconnects with exponential backoff
 * (1s, 2s, 4s ... capped at 10s) until an "end" event arrives.
 * Pass url = null to stay idle (e.g. while a snapshot is rendered instead).
 */
export function useRunStream(url: string | null, opts: { withCredentials?: boolean; snapshot?: Run | null } = {}) {
  const [state, dispatch] = useReducer(runReducer, initialRunState);
  const ended = useRef(false);
  const lastUrl = useRef<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const retry = useCallback(() => setNonce((n) => n + 1), []);
  const { withCredentials = false, snapshot = null } = opts;

  useEffect(() => {
    if (snapshot) dispatch({ kind: "snapshot", run: snapshot });
  }, [snapshot]);

  useEffect(() => {
    if (!url) return;
    if (lastUrl.current !== url) {
      lastUrl.current = url;
      dispatch({ kind: "reset" });
    }
    ended.current = false;
    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let disposed = false;

    const open = async () => {
      if (disposed) return;
      dispatch({ kind: "connecting", at: performance.now() });
      // EventSource cannot set headers, so authed streams pass the Clerk token
      // as ?token=. Fetched fresh on every (re)connect since it is short-lived.
      let target = url;
      if (withCredentials) {
        const token = await getAuthToken();
        if (token) target += `${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
        if (disposed) return;
      }
      es = new EventSource(target);
      es.onopen = () => {
        attempt = 0;
      };
      es.onmessage = (ev) => {
        let msg: StreamMessage;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (!msg || typeof msg.type !== "string") return;
        dispatch({ kind: "event", msg, at: performance.now() });
        if (msg.type === "end") {
          ended.current = true;
          es?.close();
        }
      };
      es.onerror = () => {
        if (ended.current || disposed) return;
        es?.close();
        attempt += 1;
        if (attempt > MAX_ATTEMPTS) {
          dispatch({ kind: "lost" });
          return;
        }
        dispatch({ kind: "reconnecting", attempt });
        const delay = Math.min(1000 * 2 ** (attempt - 1), 10000);
        timer = setTimeout(open, delay);
      };
    };

    open();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      es?.close();
    };
  }, [url, withCredentials, nonce]);

  return [state, dispatch, retry] as [RunState, Dispatch<RunAction>, () => void];
}
