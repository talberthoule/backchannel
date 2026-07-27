import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../services/api";
import type { DesktopUpdateStatus } from "../types";

const PORTAL_ORIGIN = "https://downloads.backchannel.page";
const GRANT_RE = /^[A-Za-z0-9_-]{43}$/;

export interface DesktopUpdateController {
  status: DesktopUpdateStatus;
  check: () => Promise<void>;
  authorize: () => Promise<void>;
  cancel: () => Promise<void>;
  apply: () => Promise<void>;
}

interface ExpectedGrant {
  source: unknown;
  nonce: string;
  version: string;
  assetId: string;
}

interface GrantMessage {
  type: "backchannel-update-grant";
  nonce: string;
  version: string;
  asset_id: string;
  grant: string;
}

export function isUpdateGrantMessage(
  event: { origin: string; source: unknown; data: unknown },
  expected: ExpectedGrant,
): event is { origin: string; source: unknown; data: GrantMessage } {
  if (
    event.origin !== PORTAL_ORIGIN
    || event.source !== expected.source
    || typeof event.data !== "object"
    || event.data === null
  ) return false;
  const data = event.data as Partial<GrantMessage>;
  return (
    data.type === "backchannel-update-grant"
    && data.nonce === expected.nonce
    && data.version === expected.version
    && data.asset_id === expected.assetId
    && typeof data.grant === "string"
    && GRANT_RE.test(data.grant)
  );
}

function freshNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function errorText(error: unknown): string {
  return error instanceof Error
    ? error.message.slice(0, 240)
    : "The update action could not be completed.";
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
    const fast = status.state === "downloading" || status.state === "applying";
    const timer = window.setInterval(() => { void refresh(); }, fast ? 1000 : pollMs);
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
    const instanceToken = tokenRef.current;
    const version = status.available_version ?? "";
    const assetId = status.platform_id ?? "";
    if (!instanceToken || !version || !assetId) {
      fail(new Error("Desktop authorization is not ready. Try again."));
      return;
    }
    const origin = new URL(window.location.origin);
    const port = Number(origin.port);
    if (
      origin.protocol !== "http:"
      || !["localhost", "127.0.0.1"].includes(origin.hostname)
      || port < 1
      || port > 65535
    ) {
      fail(new Error("Update authorization requires the local desktop app."));
      return;
    }

    actionRef.current = true;
    const nonce = freshNonce();
    const portal = new URL("/", PORTAL_ORIGIN);
    portal.search = new URLSearchParams({
      update_version: version,
      asset_id: assetId,
      origin: origin.origin,
      nonce,
    }).toString();
    const popup = window.open(
      portal.toString(),
      "_blank",
      "popup,width=720,height=760",
    );
    if (!popup) {
      actionRef.current = false;
      fail(new Error("Allow the authorization window, then try again."));
      return;
    }
    setStatus((current) => ({ ...current, state: "authorizing", error: "" }));

    let grant = "";
    try {
      grant = await new Promise<string>((resolve, reject) => {
        let settled = false;
        const finish = (error?: Error, value = "") => {
          if (settled) return;
          settled = true;
          window.removeEventListener("message", receive);
          window.clearTimeout(timeout);
          authorizationCleanupRef.current = null;
          popup.close();
          if (error) reject(error);
          else resolve(value);
        };
        const receive = (event: MessageEvent) => {
          if (isUpdateGrantMessage(event, { source: popup, nonce, version, assetId })) {
            finish(undefined, event.data.grant);
          }
        };
        const timeout = window.setTimeout(
          () => finish(new Error("Update authorization timed out. Try again.")),
          5 * 60 * 1000,
        );
        authorizationCleanupRef.current = () => finish(new Error("Authorization cancelled."));
        window.addEventListener("message", receive);
      });
      setIfMounted(await api.grantDesktopUpdate(grant, instanceToken));
    } catch (error) {
      fail(error);
    } finally {
      grant = "";
      popup.close();
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
