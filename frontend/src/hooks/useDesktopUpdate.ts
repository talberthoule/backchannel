import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../services/desktopUpdateApi";
import type {
  DesktopUpdateController,
  DesktopUpdateStatus,
} from "../types";
import { requestUpdateGrant } from "./desktopUpdateAuthorization";

export { isUpdateGrantMessage } from "./desktopUpdateAuthorization";

function errorText(error: unknown): string {
  return error instanceof Error
    ? error.message.slice(0, 240)
    : "The update action could not be completed.";
}

function authorizationTarget(
  status: DesktopUpdateStatus,
  instanceToken: string,
): [string, string, string] | null {
  const version = status.available_version ?? "";
  const assetId = status.platform_id ?? "";
  return instanceToken && version && assetId
    ? [instanceToken, version, assetId]
    : null;
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
  const authorizationCleanupRef = useRef<(() => void) | null>(null);

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
      authorizationCleanupRef.current?.();
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

  const authorize = useCallback(async () => {
    if (actionRef.current) return;
    const target = authorizationTarget(status, tokenRef.current);
    if (!target) {
      fail(new Error("Desktop authorization is not ready. Try again."));
      return;
    }
    const [instanceToken, version, assetId] = target;
    actionRef.current = true;
    setStatus((current) => ({ ...current, state: "authorizing", error: "" }));

    let grant = "";
    try {
      grant = await requestUpdateGrant(
        version,
        assetId,
        (cleanup) => {
          authorizationCleanupRef.current = cleanup;
        },
      );
      setIfMounted(await api.grantDesktopUpdate(grant, instanceToken));
    } catch (error) {
      fail(error);
    } finally {
      grant = "";
      actionRef.current = false;
    }
  }, [fail, setIfMounted, status.available_version, status.platform_id]);

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

  return { status, check, authorize, cancel, apply };
}
