const PORTAL_ORIGIN = "https://downloads.backchannel.page";
const GRANT_RE = /^[A-Za-z0-9_-]{43}$/;

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

function hasExpectedEnvelope(
  event: { origin: string; source: unknown; data: unknown },
  expected: ExpectedGrant,
): event is { origin: string; source: unknown; data: Partial<GrantMessage> } {
  return (
    event.origin === PORTAL_ORIGIN
    && event.source === expected.source
    && typeof event.data === "object"
    && event.data !== null
  );
}

export function isUpdateGrantMessage(
  event: { origin: string; source: unknown; data: unknown },
  expected: ExpectedGrant,
): event is { origin: string; source: unknown; data: GrantMessage } {
  if (!hasExpectedEnvelope(event, expected)) return false;
  return (
    event.data.type === "backchannel-update-grant"
    && event.data.nonce === expected.nonce
    && event.data.version === expected.version
    && event.data.asset_id === expected.assetId
    && typeof event.data.grant === "string"
    && GRANT_RE.test(event.data.grant)
  );
}

function freshNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function localUpdateOrigin(): URL {
  const origin = new URL(window.location.origin);
  const port = Number(origin.port);
  if (
    origin.protocol !== "http:"
    || !["localhost", "127.0.0.1"].includes(origin.hostname)
    || port < 1
    || port > 65535
  ) {
    throw new Error("Update authorization requires the local desktop app.");
  }
  return origin;
}

export async function requestUpdateGrant(
  version: string,
  assetId: string,
  setCleanup: (cleanup: (() => void) | null) => void,
): Promise<string> {
  const origin = localUpdateOrigin();
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
  if (!popup) throw new Error("Allow the authorization window, then try again.");

  try {
    return await new Promise<string>((resolve, reject) => {
      let settled = false;
      const finish = (error?: Error, value = "") => {
        if (settled) return;
        settled = true;
        window.removeEventListener("message", receive);
        window.clearTimeout(timeout);
        setCleanup(null);
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
      setCleanup(() => finish(new Error("Authorization cancelled.")));
      window.addEventListener("message", receive);
    });
  } finally {
    popup.close();
  }
}
