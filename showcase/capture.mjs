// Captures Backchannel app screenshots for the product showcase and docs.
//
// Usage:  node showcase/capture.mjs            (app running at localhost:3000)
//         node showcase/capture.mjs --out DIR  (default: showcase/screenshots)
//
// Requires: python showcase/seed_demo.py --reset
// Playwright is reused from the product-showcase skill install.
//
// Every surface is captured in both themes from deterministic fixture data.
import { createRequire } from "module";
import { homedir } from "os";
import { mkdirSync } from "fs";
import { join } from "path";

const require = createRequire(join(homedir(), ".claude/skills/product-showcase/bin/package.json"));
const { chromium } = require("playwright");

const outArg = process.argv.indexOf("--out");
const OUT = outArg > -1 ? process.argv[outArg + 1] : "showcase/screenshots";
const BASE = "http://localhost:3000";
const SESSION = "Alderwake Health Network - recovery readiness review";
const CHAT = [
  {
    role: "user",
    content: "What did we commit to, and what could still move the recovery pilot?",
  },
  {
    role: "assistant",
    content:
      "**Committed:** fixed pilot scope, managed-operations option, operating boundary, " +
      "and board-ready evidence outline by Thursday noon.\n\n" +
      "**Could move the pilot:** the ten-day identity change approval, the unconfirmed " +
      "clinical validation owner, and legal review of the managed-service boundary.",
  },
];

mkdirSync(OUT, { recursive: true });
const log = [];

async function api(path, options = {}) {
  const response = await fetch(`${BASE}/api${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`${options.method || "GET"} ${path} failed: ${response.status}`);
  }
  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

const sessions = await api("/sessions");
const demo = sessions.find((session) => session.name === SESSION);
if (!demo) throw new Error(`seeded session not found: ${SESSION}`);

const browser = await chromium.launch({
  args: [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--auto-select-desktop-capture-source=Entire screen",
  ],
});

async function openDemo(page) {
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.evaluate(
    ({ key, messages }) => sessionStorage.setItem(key, JSON.stringify(messages)),
    { key: `backchannel:meeting-chat:${demo.id}`, messages: CHAT },
  );
  const expand = page.locator('[aria-label="Expand sidebar"]');
  if (await expand.isVisible().catch(() => false)) await expand.click();
  await page.getByText(SESSION, { exact: true }).first().click();
  await page.waitForTimeout(900);
}

async function runCompleted(colorScheme, suffix) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme });
  const shot = async (name, note) => {
    await page.screenshot({ path: `${OUT}/${name}${suffix}.png` });
    log.push(`  ${name}${suffix} -- ${note}`);
  };
  const tab = async (name) => {
    await page.getByRole("button", { name }).first().click();
    await page.waitForTimeout(700);
  };

  await openDemo(page);

  await page.getByText("Top 3 Outcomes", { exact: true }).waitFor({ timeout: 20000 });
  await shot("postcall-briefing", "fixture-backed briefing rendered");

  await tab(/^Insights/);
  await page.getByText(/^ACTION ITEMS$/i).first().waitFor({ timeout: 20000 });
  const total = await page.evaluate(() =>
    document.body.innerText.match(/TOTAL\s+(\d+)/)?.[1] ?? "?");
  await shot("postcall-insights", `insight cards rendered, TOTAL ${total}`);

  await tab(/^Transcript/);
  await page.getByText(/board risk committee meets September 18/i).first().waitFor({ timeout: 20000 });
  await shot("postcall-transcript", "speaker-attributed transcript rendered");

  await tab(/^Speakers/);
  await page.getByText(/Speaker Name Mapping/i).first().waitFor({ timeout: 20000 });
  await shot("postcall-speakers", "four-speaker mapping rendered");

  await tab(/^Chat$/);
  await page.getByText(/Committed:/).first().waitFor({ timeout: 20000 });
  await shot("postcall-chat", "fixture-backed cross-meeting answer rendered");

  await page.getByText("Administration").first().click();
  await page.getByText("consolidated_analyst").first().waitFor({ timeout: 20000 });
  const badge = await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")]
      .find((candidate) => /^Agents/.test(candidate.textContent.trim()));
    return button ? button.textContent.trim() : "NOT FOUND";
  });
  await shot("admin-agents", `tab badge: ${badge}`);

  for (const [name, asset] of [
    [/Transcription & Audio/, "admin-transcription"],
    [/API Keys/, "admin-api-keys"],
    [/About/, "admin-about"],
  ]) {
    await page.getByRole("button", { name }).first().click();
    await page.waitForTimeout(700);
    await shot(asset, "admin tab");
  }

  await page.getByText("Offerings Catalog").first().click();
  const search = page.getByPlaceholder("Search offerings...");
  await search.waitFor({ timeout: 20000 });
  await search.fill("Recovery");
  await page.getByText("Recovery Readiness Assessment", { exact: true }).waitFor();
  await shot("offerings-catalog", "three recovery services rendered");

  await page.getByText("Knowledge Sources").first().click();
  const source = page.getByText("Recovery Delivery Playbooks", { exact: true }).first();
  await source.waitFor({ timeout: 20000 });
  await source.click();
  await page.getByText("Recovery readiness pilot", { exact: true }).waitFor();
  await shot("knowledge-sources", "selected playbook collection with three records");

  await page.close();
}

async function runLive(colorScheme, suffix) {
  await api(`/sessions/${demo.id}`, {
    method: "PATCH",
    body: JSON.stringify({ state: "active" }),
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme });
  try {
    await openDemo(page);
    await page.getByRole("button", { name: "Resume Audio" }).click();
    await page.getByText("Listening", { exact: true }).first().waitFor({ timeout: 20000 });
    await page.waitForTimeout(700);
    await page.screenshot({ path: `${OUT}/live-call${suffix}.png` });
    log.push(`  live-call${suffix} -- active call listening with saved insights and transcript`);
  } finally {
    await page.close();
    await api(`/sessions/${demo.id}`, {
      method: "PATCH",
      body: JSON.stringify({ state: "completed" }),
    });
  }
}

try {
  log.push("light:");
  await runCompleted("light", "");
  log.push("dark:");
  await runCompleted("dark", "-dark");
  log.push("live:");
  await runLive("light", "");
  await runLive("dark", "-dark");
} finally {
  await browser.close();
}

console.log(log.join("\n"));
console.log(`\ndone -> ${OUT}`);
