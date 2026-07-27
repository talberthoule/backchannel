import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const componentPath = fileURLToPath(new URL("./DesktopUpdate.tsx", import.meta.url));
const outputDir = await mkdtemp(join(tmpdir(), "desktop-update-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { DesktopUpdateBanner, DesktopUpdateCard } from "./DesktopUpdate.tsx";
      export { isUpdateGrantMessage } from "../hooks/useDesktopUpdate.ts";
      const noop = async () => {};
      export function renderCard(status) {
        return renderToStaticMarkup(
          React.createElement(DesktopUpdateCard, {
            update: { status, check: noop, authorize: noop, cancel: noop, apply: noop },
          }),
        );
      }
      export function renderBanner(status) {
        return renderToStaticMarkup(
          React.createElement(DesktopUpdateBanner, { status, onOpen: noop }),
        );
      }
    `,
    resolveDir: dirname(componentPath),
    sourcefile: "desktop-update-test-entry.tsx",
    loader: "tsx",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: outputPath,
});

const { isUpdateGrantMessage, renderBanner, renderCard } =
  createRequire(import.meta.url)(outputPath);

after(async () => {
  await rm(outputDir, { recursive: true, force: true });
});

const base = {
  enabled: true,
  state: "idle",
  current_version: "v1.0.0",
  available_version: "",
  available_notes: "",
  published_at: "",
  platform_id: "windows-x64",
  filename: "",
  size: 0,
  downloaded: 0,
  checked_at: "",
  error: "",
  blocked_reason: "",
};

test("unsupported source runs show no desktop update controls", () => {
  assert.equal(renderCard({ enabled: false, state: "idle" }), "");
});

test("idle and checking states expose a named check with live status", () => {
  assert.match(renderCard(base), />Check for updates</);
  const checking = renderCard({ ...base, state: "checking" });
  assert.match(checking, /aria-live="polite"/);
  assert.match(checking, /Checking for updates/);
  assert.match(checking, /disabled=""/);
});

test("available update shows signed notes, size, and download action", () => {
  const markup = renderCard({
    ...base,
    state: "available",
    available_version: "v2.0.0",
    available_notes: "## Safer updates\\n\\nAutomatic rollback.",
    filename: "Backchannel-windows-x64.zip",
    size: 10 * 1024 * 1024,
  });
  assert.match(markup, /v2\.0\.0/);
  assert.match(markup, /10 MB/);
  assert.match(markup, /Safer updates/);
  assert.match(markup, />Download update</);
});

test("expired authorization preserves progress and offers a fresh resume gesture", () => {
  const markup = renderCard({
    ...base,
    state: "needs_authorization",
    available_version: "v2.0.0",
    size: 1000,
    downloaded: 400,
  });
  assert.match(markup, /400 B of 1000 B/);
  assert.match(markup, />Resume download</);
});

test("download progress uses native progress and remains cancellable", () => {
  const markup = renderCard({
    ...base,
    state: "downloading",
    available_version: "v2.0.0",
    size: 1000,
    downloaded: 400,
  });
  assert.match(markup, /<progress[^>]+value="400"[^>]+max="1000"/);
  assert.match(markup, /400 B of 1000 B/);
  assert.match(markup, />Cancel</);
});

test("ready update explains active-work blocking and disables restart", () => {
  const markup = renderCard({
    ...base,
    state: "ready",
    available_version: "v2.0.0",
    size: 1000,
    downloaded: 1000,
    blocked_reason: "audio import",
  });
  assert.match(markup, /Finish audio import before installing/);
  assert.match(markup, /disabled=""/);
  assert.match(markup, />Restart and install</);
});

test("errors stay bounded and retryable", () => {
  const markup = renderCard({ ...base, state: "error", error: "E".repeat(5000) });
  assert.ok(markup.length < 2000);
  assert.match(markup, />Retry</);
});

test("banner appears only for actionable states with a native button", () => {
  assert.equal(renderBanner(base), "");
  for (const state of ["available", "downloading", "ready"]) {
    const markup = renderBanner({
      ...base,
      state,
      available_version: "v2.0.0",
      size: 1000,
      downloaded: state === "ready" ? 1000 : 400,
    });
    assert.match(markup, /<button/);
    assert.match(markup, /v2\.0\.0/);
  }
});

test("grant messages require exact origin, popup, request, and token", () => {
  const popup = {};
  const expected = {
    source: popup,
    nonce: "a".repeat(32),
    version: "v2.0.0",
    assetId: "windows-x64",
  };
  const data = {
    type: "backchannel-update-grant",
    nonce: expected.nonce,
    version: expected.version,
    asset_id: expected.assetId,
    grant: "g".repeat(43),
  };
  const event = {
    origin: "https://downloads.backchannel.page",
    source: popup,
    data,
  };
  assert.equal(isUpdateGrantMessage(event, expected), true);
  for (const bad of [
    { ...event, origin: "https://downloads.backchannel.page.attacker.example" },
    { ...event, source: {} },
    { ...event, data: { ...data, type: "other" } },
    { ...event, data: { ...data, nonce: "b".repeat(32) } },
    { ...event, data: { ...data, version: "v2.0.1" } },
    { ...event, data: { ...data, asset_id: "linux-x64" } },
    { ...event, data: { ...data, grant: "short" } },
  ]) {
    assert.equal(isUpdateGrantMessage(bad, expected), false);
  }
});
