import type { DesktopUpdateStatus } from "../types";
import { request } from "./api";

const BASE = "/api";

export const getDesktopUpdate = () => request<DesktopUpdateStatus>("/updates");

export async function getDesktopInstanceToken(): Promise<string> {
  const response = await fetch(`${BASE}/health`, { cache: "no-store" });
  if (!response.ok) throw new Error("Desktop authorization is unavailable.");
  const body: unknown = await response.json();
  if (
    typeof body !== "object"
    || body === null
    || Object.keys(body).length !== 1
    || (body as { status?: unknown }).status !== "ok"
  ) {
    throw new Error("Desktop authorization is unavailable.");
  }
  const token = response.headers.get("X-Backchannel-Instance") ?? "";
  if (!/^[A-Za-z0-9_-]{43}$/.test(token)) {
    throw new Error("Desktop authorization is unavailable.");
  }
  return token;
}

const mutation = (
  path: string,
  method: "POST" | "DELETE",
  token: string,
  body?: unknown,
) => request<DesktopUpdateStatus>(path, {
  method,
  headers: {
    "Content-Type": "application/json",
    "X-Backchannel-Instance": token,
  },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const checkDesktopUpdate = (token: string) =>
  mutation("/updates/check", "POST", token);

export const startDesktopUpdateDownload = (token: string) =>
  mutation("/updates/download", "POST", token);

export const cancelDesktopUpdate = (token: string) =>
  mutation("/updates/download", "DELETE", token);

export const applyDesktopUpdate = (token: string) =>
  mutation("/updates/apply", "POST", token);
