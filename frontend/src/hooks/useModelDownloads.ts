import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../services/api";
import type { ModelDownload, ModelDownloadsStatus } from "../types";

const IDLE_POLL_MS = 20000;
const ACTIVE_POLL_MS = 1500;

const EMPTY: ModelDownloadsStatus = { downloads: [], active: 0, failed: 0 };

export interface ModelDownloadsController {
  status: ModelDownloadsStatus;
  /** Queued or downloading, newest first. */
  active: ModelDownload[];
  /** Failed and not yet dismissed. */
  failed: ModelDownload[];
  refresh: () => Promise<void>;
  retry: (key: string) => Promise<void>;
  dismiss: (key: string) => Promise<void>;
}

/**
 * Polls what the backend is fetching.
 *
 * Fast while something is in flight, slow when nothing is, so an idle app is
 * not paying for a download poller it does not need. A failed entry keeps
 * being reported until someone dismisses or retries it: a download that
 * silently gave up is the thing this whole surface exists to prevent.
 */
export function useModelDownloads(): ModelDownloadsController {
  const [status, setStatus] = useState<ModelDownloadsStatus>(EMPTY);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stopped = useRef(false);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.getModelDownloads());
    } catch {
      // A poll that cannot reach the backend says nothing new; keep the last
      // reading rather than blanking a download the user is watching.
    }
  }, []);

  useEffect(() => {
    stopped.current = false;
    let cancelled = false;

    const tick = async () => {
      let next = IDLE_POLL_MS;
      try {
        const fresh = await api.getModelDownloads();
        if (cancelled) return;
        setStatus(fresh);
        next = fresh.active > 0 ? ACTIVE_POLL_MS : IDLE_POLL_MS;
      } catch {
        // Keep polling; the backend may just be starting.
      }
      if (!cancelled && !stopped.current) timer.current = setTimeout(() => void tick(), next);
    };

    void tick();
    return () => {
      cancelled = true;
      stopped.current = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const retry = useCallback(async (key: string) => {
    await api.retryModelDownload(key);
    await refresh();
  }, [refresh]);

  const dismiss = useCallback(async (key: string) => {
    await api.dismissModelDownload(key);
    await refresh();
  }, [refresh]);

  return {
    status,
    active: status.downloads.filter((d) => d.state === "queued" || d.state === "downloading"),
    failed: status.downloads.filter((d) => d.state === "error"),
    refresh,
    retry,
    dismiss,
  };
}
