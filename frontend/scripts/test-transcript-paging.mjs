// Run after npm run build. Uses synthetic transcripts, never a running call.
// node scripts/test-transcript-paging.mjs [path to an installed playwright package]
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const require = createRequire(import.meta.url);
const { chromium } = require(process.argv[2] || "playwright");
const assets = new URL("../dist/assets/", import.meta.url);
const css = readFileSync(new URL(readdirSync(assets).find(file => file.endsWith(".css")), assets), "utf8");
const bundle = await build({
  stdin: {
    contents: `
      import React, { useCallback, useMemo, useState } from "react";
      import { createRoot } from "react-dom/client";
      import TranscriptPanel from "./TranscriptPanel";
      const make = (count) => Array.from({ length: count }, (_, i) => ({
        id: String(i), text: "Speech number " + i + (i === 3 || i === count - 3 ? " needle" : ""),
        timestamp: new Date(1700000000000 + i * 1000).toISOString(), speaker_id: "s1",
      }));
      function Harness({ count }) {
        const [saved, setSaved] = useState(() => make(count));
        const [interim, setInterim] = useState("In progress");
        const [tick, setTick] = useState(0);
        const [collapsed, setCollapsed] = useState(false);
        const [speakers, setSpeakers] = useState([{ id: "s1", name: "Speaker 1", color: "#123456" }]);
        const toggle = useCallback(() => setCollapsed(v => !v), []);
        const transcripts = useMemo(() => [...saved, { text: interim, timestamp: "2026-09-10T00:00:00Z", interim: true }], [saved, interim]);
        window.bump = () => setTick(v => v + 1);
        window.interim = setInterim;
        window.append = () => setSaved(items => [...items, { ...make(1)[0], id: "new", text: "New final speech" }]);
        window.shrink = () => setSaved(make(5));
        window.rename = () => setSpeakers([{ id: "s1", name: "Renamed speaker", color: "#123456" }]);
        return <div data-tick={tick} data-count={count} style={{ height: '100vh' }}>
          <TranscriptPanel transcripts={transcripts} speakers={speakers} collapsed={collapsed} onToggleCollapse={toggle} />
        </div>;
      }
      const root = createRoot(document.getElementById('root'));
      let generation = 0;
      window.mount = count => root.render(<Harness key={++generation} count={count} />);
    `,
    resolveDir: fileURLToPath(new URL("../src/components/ActiveCall/", import.meta.url)),
    loader: "tsx",
  },
  bundle: true, write: false, format: "iife", platform: "browser",
  define: { "process.env.NODE_ENV": '"production"' },
});

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 900, height: 800 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.setContent(`<html><head><style>${css}</style></head><body><div id="root"></div></body></html>`);
  await page.evaluate(() => {
    window.formatCalls = 0;
    const descriptor = Object.getOwnPropertyDescriptor(Intl.DateTimeFormat.prototype, "format");
    Object.defineProperty(Intl.DateTimeFormat.prototype, "format", {
      ...descriptor, get() { window.formatCalls++; return descriptor.get.call(this); },
    });
  });
  await page.addScriptTag({ content: bundle.outputFiles[0].text });
  const rows = page.locator("[data-entry-index]");
  const entries = page.getByRole("region", { name: "Live transcription entries", exact: true });
  const mount = async count => {
    await page.evaluate(count => window.mount(count), count);
    await page.waitForFunction(count => document.querySelector('[data-count="' + count + '"]')
      && document.querySelectorAll('[data-entry-index]').length === 40, count);
  };

  await mount(1036);
  assert.equal(await rows.count(), 40);
  assert.equal(await rows.first().getAttribute("data-entry-index"), "997");
  await page.evaluate(() => { window.formatCalls = 0; window.bump(); });
  await page.waitForFunction(() => document.querySelector('[data-tick="1"]'));
  assert.equal(await page.evaluate(() => window.formatCalls), 0);
  await page.evaluate(() => window.interim("Updated interim speech"));
  await page.getByText("Updated interim speech").waitFor({ state: "attached" });
  assert.equal(await page.evaluate(() => window.formatCalls), 1, "only interim row may render");
  await page.evaluate(() => window.append());
  await page.getByText("New final speech", { exact: true }).waitFor();
  assert.equal(await rows.count(), 40);
  assert.equal(await entries.evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight < 3), true);

  // Scrolling up freezes the existing window without jumping to its top.
  await entries.evaluate(el => { el.scrollTop = Math.floor((el.scrollHeight - el.clientHeight) / 2); });
  await page.waitForFunction(() => !document.querySelector('[aria-label="Live transcript entries"]').disabled);
  const heldIndex = await rows.first().getAttribute("data-entry-index");
  const heldScroll = await entries.evaluate(el => el.scrollTop);
  assert.ok(heldScroll > 0);
  await page.evaluate(() => window.interim("Another interim"));
  await page.getByText("Another interim").waitFor({ state: "attached" });
  assert.equal(await rows.first().getAttribute("data-entry-index"), heldIndex);
  assert.equal(await entries.evaluate(el => el.scrollTop), heldScroll);

  await page.getByRole("button", { name: "First transcript entries", exact: true }).click();
  assert.equal(await rows.first().getAttribute("data-entry-index"), "0");
  await page.evaluate(() => { window.formatCalls = 0; window.interim("Hidden interim"); window.bump(); });
  await page.waitForFunction(() => document.querySelector('[data-tick="2"]'));
  assert.equal(await page.evaluate(() => window.formatCalls), 0, "history must not redraw for interim speech");
  assert.equal(await rows.first().getAttribute("data-entry-index"), "0");
  await page.getByRole("button", { name: "Newer transcript entries", exact: true }).focus();
  await page.keyboard.press("Enter");
  assert.equal(await rows.first().getAttribute("data-entry-index"), "40");
  await page.getByRole("button", { name: "Older transcript entries", exact: true }).click();
  assert.equal(await rows.first().getAttribute("data-entry-index"), "0");

  // Search scans ALL saved entries and brings off-page matches into the window.
  await entries.focus();
  await page.keyboard.press("Control+f");
  await page.getByRole("textbox", { name: "Search live transcript" }).fill("needle");
  await page.locator('[data-entry-index="3"] mark').waitFor();
  await page.getByRole("button", { name: "Next match", exact: true }).click();
  await page.locator('[data-entry-index="1033"] mark').waitFor();
  assert.equal(await rows.count(), 40);
  await page.getByRole("textbox", { name: "Search live transcript" }).press("Shift+Enter");
  await page.locator('[data-entry-index="3"] mark').waitFor();
  await page.getByRole("textbox", { name: "Search live transcript" }).press("Escape");
  await page.getByText("Hidden interim").waitFor({ state: "attached" });
  assert.equal(await entries.evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight < 3), true);

  await page.evaluate(() => window.rename());
  await page.getByText("Renamed speaker", { exact: true }).first().waitFor();
  await page.getByTitle("Hide live transcription", { exact: true }).click();
  assert.equal(await rows.count(), 0);
  await page.evaluate(() => window.interim("While collapsed"));
  await page.getByTitle("Show live transcription", { exact: true }).click();
  await page.getByText("While collapsed").waitFor({ state: "attached" });
  assert.equal(await rows.count(), 40);
  await page.getByRole("button", { name: "Older transcript entries", exact: true }).click();
  await page.evaluate(() => window.shrink());
  await page.waitForFunction(() => document.querySelectorAll('[data-entry-index]').length === 6);
  assert.equal(await rows.first().getAttribute("data-entry-index"), "0");

  await mount(10000);
  assert.equal(await rows.count(), 40);
  for (const width of [320, 900]) {
    await page.setViewportSize({ width, height: 800 });
    for (const theme of ["light", "dark"]) {
      await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(await page.getByRole("navigation", { name: "Transcript pages" }).evaluate(el => el.getBoundingClientRect().bottom <= innerHeight), true);
    }
  }
  assert.deepEqual(errors, []);
  console.log("PASS: transcript bound at 40; interim/history memoization; live follow, history hold, keyboard paging, full-history search, speakers, collapse, shrink, 10000 rows and mobile/dark layout.");
} finally {
  await browser.close();
}
