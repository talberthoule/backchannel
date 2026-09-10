// Browser regression harness. Uses synthetic data only; never connects to a call.
// Run after npm run build:
// node scripts/test-insight-paging.mjs [path to an installed playwright package]
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const require = createRequire(import.meta.url);
const { chromium } = require(process.argv[2] || "playwright");
const assets = new URL("../dist/assets/", import.meta.url);
const css = readFileSync(new URL(readdirSync(assets).find((file) => file.endsWith(".css")), assets), "utf8");
const bundle = await build({
  stdin: {
    contents: `
      import React, { useCallback, useState } from "react";
      import { createRoot } from "react-dom/client";
      import QuestionList from "./QuestionList";
      const make = (count) => Array.from({ length: count }, (_, i) => ({
        id: String(i), question: "Insight number " + i,
        item_type: i < 18 ? "action_item" : "observation",
        created_at: new Date(1700000000000 + i * 1000).toISOString(),
        starred: false, dismissed: false, vote: 0, rationale: "Supporting detail " + i,
      }));
      function Harness({ count }) {
        const [questions, setQuestions] = useState(() => make(count));
        const [tick, setTick] = useState(0);
        const change = useCallback((id, patch) => setQuestions(items =>
          items.map(q => q.id === id ? { ...q, ...patch } : q)), []);
        const star = useCallback((id, starred) => change(id, { starred }), [change]);
        const dismiss = useCallback(id => change(id, { dismissed: true }), [change]);
        const vote = useCallback((id, vote) => change(id, { vote }), [change]);
        window.bump = () => setTick(t => t + 1);
        window.change = change;
        window.append = () => setQuestions(items => [...items, {
          ...make(1)[0], id: 'new', question: 'New insight', created_at: '2026-09-10T00:00:00Z',
        }]);
        return <div data-tick={tick} data-count={count} style={{ height: '100vh' }}>
          <QuestionList questions={questions} onStar={star} onDismiss={dismiss} onVote={vote} />
        </div>;
      }
      const root = createRoot(document.getElementById('root'));
      let generation = 0;
      window.mount = (count) => root.render(<Harness key={++generation} count={count} />);
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
  const cards = page.getByRole("button", { name: "Dismiss", exact: true });
  const mount = async (count) => {
    await page.evaluate(count => window.mount(count), count);
    await page.waitForFunction(count =>
      document.querySelector('[data-count="' + count + '"]')
      && document.querySelectorAll('[aria-label="Dismiss"]').length === Math.min(count, 40), count);
  };

  await mount(860);
  assert.equal(await cards.count(), 40);
  assert.equal(await page.getByRole("status").innerText(), "1-40 of 860 insights");
  await page.evaluate(() => { window.formatCalls = 0; window.bump(); });
  await page.waitForFunction(() => document.querySelector('[data-tick="1"]'));
  assert.equal(await page.evaluate(() => window.formatCalls), 0, "unrelated updates must not render cards");
  await page.evaluate(() => window.change("859", { question: "Updated insight" }));
  await page.getByText("Updated insight", { exact: true }).waitFor();
  assert.equal(await page.evaluate(() => window.formatCalls), 2, "only the changed card should format dates");

  await page.getByRole("button", { name: "Next insight page", exact: true }).focus();
  await page.keyboard.press("Enter");
  await page.getByText("Insight number 819", { exact: true }).waitFor();
  assert.equal(await cards.count(), 40);
  assert.equal(await page.getByRole("status").innerText(), "41-80 of 860 insights");
  await page.getByRole("button", { name: "Last insight page", exact: true }).click();
  await page.getByText("Insight number 0", { exact: true }).waitFor();
  assert.equal(await cards.count(), 20);
  assert.equal(await page.getByRole("status").innerText(), "841-860 of 860 insights");
  await page.getByRole("button", { name: /^Action Items/ }).click();
  assert.equal(await cards.count(), 18);
  assert.equal(await page.getByRole("navigation", { name: "Insight pages" }).count(), 0);
  await page.getByRole("button", { name: /^All / }).click();
  assert.equal(await cards.count(), 40);
  assert.equal(await page.getByRole("status").innerText(), "1-40 of 860 insights");

  // Card controls retain their real callbacks and expanded content.
  await page.getByRole("button", { name: "Details", exact: true }).first().click();
  await page.getByText("Supporting detail 859", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Star", exact: true }).first().click();
  assert.equal(await page.getByRole("button", { name: "Unstar", exact: true }).count(), 1);
  await page.getByRole("button", { name: "Upvote insight", exact: true }).first().click();
  await page.getByText("+1", { exact: true }).waitFor();

  await mount(41);
  await page.getByRole("button", { name: "Last insight page", exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('[aria-label="Dismiss"]').length === 1);
  await cards.click();
  await page.waitForFunction(() => document.querySelectorAll('[aria-label="Dismiss"]').length === 40);
  await page.evaluate(() => window.append());
  await page.getByText("New insight", { exact: true }).waitFor();
  assert.equal(await page.getByRole("status").innerText(), "1-40 of 41 insights");

  await mount(10000);
  assert.equal(await cards.count(), 40);
  assert.equal(await page.getByRole("status").innerText(), "1-40 of 10000 insights");
  for (const width of [320, 900]) {
    await page.setViewportSize({ width, height: 800 });
    for (const theme of ["light", "dark"]) {
      await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${width}px ${theme} overflow`);
      const controls = page.getByRole("navigation", { name: "Insight pages" });
      assert.equal(await controls.evaluate(el => el.getBoundingClientRect().bottom <= innerHeight), true, "paging must remain visible");
      assert.equal(await cards.first().evaluate(el => getComputedStyle(el.closest('.rounded-lg')).animationName), "none");
      if (process.env.BACKCHANNEL_INSIGHT_SCREENSHOT && width === 320 && theme === "dark") {
        await page.screenshot({ path: process.env.BACKCHANNEL_INSIGHT_SCREENSHOT });
      }
    }
  }
  assert.deepEqual(errors, []);
  console.log("PASS: 860/10000 insights bounded at 40; memoized updates; paging, filters, keyboard, card actions, last-page dismissal, mobile/dark layout.");
} finally {
  await browser.close();
}
