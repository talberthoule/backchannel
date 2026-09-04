import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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
      import * as desktopUpdateHook from "../hooks/useDesktopUpdate.ts";
      export const finishUpdateWindow = desktopUpdateHook.finishUpdateWindow;
      const noop = async () => {};
      export function renderCard(status) {
        return renderToStaticMarkup(
          React.createElement(DesktopUpdateCard, {
            update: { status, check: noop, download: noop, cancel: noop, apply: noop },
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

const { finishUpdateWindow, isUpdateGrantMessage, renderBanner, renderCard } =
  createRequire(import.meta.url)(outputPath);

const adminSource = readFileSync(new URL("./AdminPanel.tsx", import.meta.url), "utf8");
const managementSource = readFileSync(new URL("./ManagementView.tsx", import.meta.url), "utf8");
const appSource = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
const hookSource = readFileSync(new URL("../hooks/useDesktopUpdate.ts", import.meta.url), "utf8");

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

test("available update keeps the action visible above collapsed release notes", () => {
  const markup = renderCard({
    ...base,
    state: "available",
    available_version: "v2.0.0",
    available_notes: "## A long release\n\n" + "Detail. ".repeat(500),
    size: 10 * 1024 * 1024,
  });
  const action = markup.indexOf(">Download update");
  const notes = markup.indexOf("<details");
  assert.ok(action >= 0 && notes > action, "download should stay above the notes disclosure");
  assert.match(markup, /<summary[^>]*>Review what(?:&#x27;|&apos;|')s included<\/summary>/);
  assert.doesNotMatch(markup, /<details[^>]* open/);
});

test("the parent owns the active admin tab used to suppress the update banner", () => {
  assert.doesNotMatch(adminSource, /useState<AdminTab>/);
  assert.match(adminSource, /activeTab: AdminTab/);
  assert.match(adminSource, /onTabChange: \(tab: AdminTab\) => void/);
  assert.match(managementSource, /activeTab=\{adminTab\}/);
  assert.match(managementSource, /onTabChange=\{onAdminTabChange\}/);
  assert.match(appSource, /onAdminTabChange=\{setAdminTab\}/);
});

test("an accepted install closes the old app window before the launcher reopens it", () => {
  assert.equal(typeof finishUpdateWindow, "function");
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  let closed = 0;
  let delay = null;
  globalThis.window = {
    close: () => { closed += 1; },
    setTimeout: (callback, timeout) => {
      delay = timeout;
      callback();
      return 1;
    },
  };
  globalThis.document = { title: "Backchannel" };
  try {
    finishUpdateWindow();
    assert.equal(globalThis.document.title, "Backchannel - Installing update");
    assert.equal(delay, 50);
    assert.equal(closed, 1);
    assert.match(hookSource, /state === "applying"[\s\S]*finishUpdateWindow\(\)/);
  } finally {
    globalThis.window = previousWindow;
    globalThis.document = previousDocument;
  }
});

test("an interrupted download preserves progress and offers a fresh resume gesture", () => {
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

// Updating used to hand the user off to the release portal for an
// authorization grant, and the portal answered with a login panel: a sign-in
// wall in front of a build the same portal gives to anyone. Nothing in this
// card may send the reader anywhere to prove who they are.
test("updating never routes the user through a sign-in", () => {
  for (const state of ["available", "downloading", "needs_authorization", "ready", "error"]) {
    const markup = renderCard({
      ...base,
      state,
      available_version: "v2.0.0",
      size: 1000,
      downloaded: 400,
    });
    assert.doesNotMatch(markup, /downloads\.backchannel\.page/);
    assert.doesNotMatch(markup, /sign in|sign-in|log in|account/i);
    assert.doesNotMatch(markup, /authoriz/i, `authorization language survived in "${state}"`);
    assert.doesNotMatch(markup, /<a/, `the card opened a link in "${state}"`);
  }
});
