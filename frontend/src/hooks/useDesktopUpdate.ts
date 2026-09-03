import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../services/desktopUpdateApi";
import type {
  DesktopUpdateController,
  DesktopUpdateStatus,
} from "../types";
function errorText(error: unknown): string {
  return error instanceof Error
    ? error.message.slice(0, 240)
    : "The update action could not be completed.";
}

function pollingInterval(state: DesktopUpdateStatus["state"], pollMs: number): number {
  return state === "downloading" || state === "applying" ? 1000 : pollMs;
}

export function useDesktopUpdate(pollMs = 5000): DesktopUpdateController {
  const [status, setStatus] = useState<DesktopUpdateStatus>({
    enabled: false,
    state: "idle",
  });
  const tokenRef = useRef("");
  const actionRef = useRef(false);
  const mountedRef = useRef(true);

  const setIfMounted = useCallback((next: DesktopUpdateStatus) => {
    if (mountedRef.current) setStatus(next);
  }, []);

  const fail = useCallback((error: unknown) => {
    if (!mountedRef.current) return;
    setStatus((current) => ({
      ...current,
      enabled: true,
      state: "error",
      error: errorText(error),
    }));
  }, []);

  const refresh = useCallback(async () => {
    if (actionRef.current) return;
    try {
      setIfMounted(await api.getDesktopUpdate());
    } catch {
      // A transient status poll must not erase the last actionable state.
    }
  }, [setIfMounted]);

  const token = useCallback(async () => {
    if (!tokenRef.current) tokenRef.current = await api.getDesktopInstanceToken();
    return tokenRef.current;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void refresh();
    void api.getDesktopInstanceToken()
      .then((value) => { tokenRef.current = value; })
      .catch(() => {});
    return () => {
      mountedRef.current = false;
    };
  }, [refresh]);

  useEffect(() => {
    const timer = window.setInterval(
      () => { void refresh(); },
      pollingInterval(status.state, pollMs),
    );
    return () => window.clearInterval(timer);
  }, [pollMs, refresh, status.state]);

  const check = useCallback(async () => {
    if (actionRef.current) return;
    actionRef.current = true;
    setStatus((current) => ({ ...current, enabled: true, state: "checking", error: "" }));
    try {
      setIfMounted(await api.checkDesktopUpdate(await token()));
    } catch (error) {
      fail(error);
    } finally {
      actionRef.current = false;
    }
  }, [fail, setIfMounted, token]);

  // Starts the transfer outright. There is no authorization step: the update
  // asset is served anonymously, the same way the release portal serves it.
  const download = useCallback(async () => {
    if (actionRef.current) return;
    actionRef.current = true;
    setStatus((current) => ({ ...current, state: "downloading", error: "" }));
    try {
      setIfMounted(await api.startDesktopUpdateDownload(await token()));
    } catch (error) {
      fail(error);
    } finally {
      actionRef.current = false;
    }
  }, [fail, setIfMounted, token]);

  const cancel = useCallback(async () => {
    if (actionRef.current) return;
    actionRef.current = true;
    try {
      setIfMounted(await api.cancelDesktopUpdate(await token()));
    } catch (error) {
      fail(error);
    } finally {
      actionRef.current = false;
    }
  }, [fail, setIfMounted, token]);

  const apply = useCallback(async () => {
    if (actionRef.current) return;
    actionRef.current = true;
    try {
      setIfMounted(await api.applyDesktopUpdate(await token()));
    } catch (error) {
      fail(error);
    } finally {
      actionRef.current = false;
    }
  }, [fail, setIfMounted, token]);

  return { status, check, download, cancel, apply };
}
