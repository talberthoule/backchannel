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
// Aim BACKCHANNEL_SHOWCASE_BASE at the isolated capture stack
// (showcase/docker-compose.capture.yml) rather than the long-lived dev stack.
const BASE = process.env.BACKCHANNEL_SHOWCASE_BASE || "http://localhost:3000";
const SESSION = "Alderwake Health Network - recovery readiness review";
const PRECALL_SESSION = "Alderwake Health Network - pilot scope review";
// The sentence the PII Shield preview is run on. Kept inside the fictional
// Alderwake story rather than using the card's shipped sample, so the whole
// asset family reads as one call. It exercises both detection routes: the
// on-device model finds the person and the organization, patterns find the
// email and the phone number.
//
// The number is a full ten digits in the 555-01xx range reserved for fiction.
// A seven-digit number is below the phone pattern's threshold and survives
// into the output, which reads on a marketing crop as a miss rather than as
// the deliberate scope it is.
const PII_SAMPLE =
  "Owen Delacroix from Alderwake Health Network owns the identity approval. " +
  "Reach him at owen.delacroix@alderwake.example or 212-555-0142 before the board review.";
// Matches the model named in the seeded asked rows' "Answered by" caption.
const ASK_MODEL = "gemini-3.6-flash";
const ASK_DRAFT = "What did Owen commit to sending tomorrow?";
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
const CLEAN_CREDENTIALS = ["google", "openai", "openai-compatible"].map((provider) => ({
  provider,
  configured: false,
  env_fallback: false,
  masked: "",
  connected: false,
}));

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

async function waitForAudioTeardown() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const segments = await api(`/sessions/${demo.id}/segments`);
    if (segments.every((segment) => segment.ended_at)) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("live capture audio segment did not close");
}

const sessions = await api("/sessions");
const demo = sessions.find((session) => session.name === SESSION);
if (!demo) throw new Error(`seeded session not found: ${SESSION}`);

// The fixture is written through APIs before the shield is ever on, so its
// vault starts empty and the Privacy card would report "0 protected values"
// while claiming to protect. Running the documented path for data recorded
// before the shield existed fills it: the demo session's names and identifiers
// move into the encrypted vault and the rows keep tokens.
//
// The shield is handed straight back off, because every other surface should
// be captured in the state a new install is actually in. What survives is the
// vault and the tokenized rows - so each later shot showing real names on
// screen is itself the evidence that reveal-at-the-edge works.
async function protectDemoSession() {
  await api("/pii-shield", { method: "PUT", body: JSON.stringify({ enabled: true }) });
  try {
    const result = await api(`/sessions/${demo.id}/pii/protect`, { method: "POST" });
    log.push(`vault: ${result.vault_entries} protected values from the demo session`);
  } finally {
    await api("/pii-shield", { method: "PUT", body: JSON.stringify({ enabled: false }) });
  }
}

await protectDemoSession();

const browser = await chromium.launch({
  args: [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--auto-select-desktop-capture-source=Entire screen",
  ],
});

// The review pane is the scrolling element, not the window: find it by overflow
// rather than by class, so a Tailwind change does not silently stop scrolling.
async function scrollPane(page, top) {
  await page.evaluate((offset) => {
    const pane = [...document.querySelectorAll("*")]
      .filter((node) => {
        const style = getComputedStyle(node);
        return (
          /auto|scroll/.test(style.overflowY) &&
          node.scrollHeight > node.clientHeight + 50 &&
          node.clientHeight > 300
        );
      })
      .sort((a, b) => b.scrollHeight - b.clientHeight - (a.scrollHeight - a.clientHeight))[0];
    if (pane) pane.scrollTop = offset;
  }, top);
}

// A sidebar row's accessible name is the session name plus its state, which
// the row carries as screen-reader-only text (sessionStateLabel in
// frontend/src/components/Layout.tsx). Matching on the pair rather than the
// name alone keeps the click on the intended row now that the fixture seeds
// several sessions whose names share a prefix.
//
// The name and the state sit in sibling spans, so the accessible name is
// their concatenation with a space between - "<name> , Completed", not
// "<name>, Completed". A regex spans that gap instead of guessing at it.
async function openSession(page, name, state) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const row = page
    .getByRole("button", { name: new RegExp(`^${escaped}\\s*,\\s*${state}$`) })
    .first();
  await row.waitFor({ timeout: 20000 });
  await row.click();
  await page.waitForTimeout(900);
}

async function openDemo(page) {
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.evaluate(
    ({ key, messages, askKey, askModel }) => {
      sessionStorage.setItem(key, JSON.stringify(messages));
      // The ask bar's model is an explicit per-session choice held in
      // localStorage; without it every live shot reads "Select model".
      localStorage.setItem(askKey, askModel);
    },
    {
      key: `backchannel:meeting-chat:${demo.id}`,
      messages: CHAT,
      askKey: `backchannel:ask-model:${demo.id}`,
      askModel: ASK_MODEL,
    },
  );
  // The sidebar opens expanded by default since v0.5.4 and remembers a
  // collapse per origin; a fresh Playwright context never collapsed it, but
  // the guard costs nothing and keeps the script honest on a reused profile.
  const expand = page.locator('[aria-label="Expand sidebar"]');
  if (await expand.isVisible().catch(() => false)) await expand.click();
  await openSession(page, SESSION, "Completed");
}

async function useCleanConnections(page) {
  await page.route(`${BASE}/api/credentials`, (route) =>
    route.fulfill({ json: CLEAN_CREDENTIALS }));
  await page.route(`${BASE}/api/endpoints`, (route) =>
    route.fulfill({ json: [] }));
}

async function runCompleted(colorScheme, suffix) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme });
  await useCleanConnections(page);
  const shot = async (name, note) => {
    await page.screenshot({ path: `${OUT}/${name}${suffix}.png` });
    log.push(`  ${name}${suffix} -- ${note}`);
  };
  const tab = async (name) => {
    await page.getByRole("tab", { name }).first().click();
    await page.waitForTimeout(700);
  };

  await openDemo(page);

  // A completed session opens on the Overview (v0.5.4): the briefing's top
  // outcome, the counts row, the digest, participation, and call rhythm. The
  // spend tile fetches usage and pricing after mount, so wait for its token
  // count rather than shooting a pulse placeholder.
  await page.getByText("Top outcome from the briefing.", { exact: true }).waitFor({ timeout: 20000 });
  await page.getByText(/^[\d,]+ tokens$/).first().waitFor({ timeout: 20000 });
  await page.waitForTimeout(400);
  await shot("postcall-overview", "Overview worksheet with the spend tile priced");

  // The same page, scrolled to the digest lists and the two measured panels.
  await scrollPane(page, 560);
  await page.waitForTimeout(400);
  await shot("postcall-overview-digest", "Overview digest, participation and call rhythm");
  await scrollPane(page, 0);

  await tab(/^Briefing/);
  await page.getByText("Top outcomes", { exact: true }).waitFor({ timeout: 20000 });
  await shot("postcall-briefing", "fixture-backed briefing typeset as one sheet");

  // Signals raised during the call are kept, so they can still be read here
  // (ALP-244). Expanded and scrolled to, because the panel sits below the fold.
  const history = page.getByRole("button", { name: /^History \(\d+\)$/ }).first();
  await history.waitFor({ timeout: 20000 });
  await history.scrollIntoViewIfNeeded();
  await history.click();
  const hide = page.getByRole("button", { name: "Hide history" }).first();
  await hide.waitFor({ timeout: 20000 });
  await hide.scrollIntoViewIfNeeded();
  await page.waitForTimeout(600);
  await shot("postcall-signals", "kept strategic signals expanded");
  await hide.click();
  await scrollPane(page, 0);

  await tab(/^Insights/);
  await page.getByText(/^ACTION ITEMS$/i).first().waitFor({ timeout: 20000 });
  const total = await page.evaluate(() =>
    document.body.innerText.match(/TOTAL\s+(\d+)/)?.[1] ?? "?");
  await shot("postcall-insights", `insight cards rendered, TOTAL ${total}`);

  // Scrolled past the type tiles to the cards themselves: this is where an
  // insight shows the speaker it came from and the agent that produced it.
  // A fixed offset into the review pane, not a locator: every "ACTION ITEMS"
  // string on this page is already in view inside a count tile, so
  // scrollIntoViewIfNeeded is a no-op. The fixture is deterministic, so the
  // distance is too. The pane scrolls, not the window.
  await scrollPane(page, 890);
  await page.waitForTimeout(500);
  await shot("postcall-attributed", "speaker-attributed insight cards");
  await scrollPane(page, 0);

  await tab(/^Transcript/);
  await page.getByText(/board risk committee meets September 18/i).first().waitFor({ timeout: 20000 });
  await shot("postcall-transcript", "speaker-attributed transcript rendered");

  await tab(/^Speakers/);
  await page.getByText(/Speaker Name Mapping/i).first().waitFor({ timeout: 20000 });
  await shot("postcall-speakers", "four-speaker mapping rendered");

  await tab(/^Chat$/);
  await page.getByText(/Committed:/).first().waitFor({ timeout: 20000 });
  await shot("postcall-chat", "fixture-backed cross-meeting answer rendered");

  // Usage by source and by model, with cached and audio slices priced at
  // their own rates (v0.5.4). Pricing arrives after the usage does; the
  // session estimate row is the last thing to render.
  await tab(/^Tokens/);
  await page.getByText("Session estimate", { exact: true }).first().waitFor({ timeout: 20000 });
  await page.waitForTimeout(400);
  await shot("postcall-tokens", "token usage by source and model, priced");

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
    [/Connections/, "admin-api-keys"],
    [/About/, "admin-about"],
  ]) {
    await page.getByRole("button", { name }).first().click();
    if (asset === "admin-api-keys") {
      await page.getByText("Not configured", { exact: true }).first().waitFor();
      await page.getByText("No self-hosted endpoints yet.", { exact: true }).waitFor();
    }
    if (asset === "admin-about") {
      await page.getByText("Current", { exact: true }).first().waitFor({ timeout: 20000 });
      await page.getByText("Loading model pricing...", { exact: true }).waitFor({ state: "detached", timeout: 20000 });
    }
    await page.waitForTimeout(700);
    await shot(asset, asset === "admin-api-keys" ? "clean Connections fixture" : "admin tab");
  }

  // Privacy: the PII Shield turned on, so the coverage list reports on a
  // running configuration rather than an inert switch. The shield is a
  // workspace setting, so it is turned back off in the finally below - the
  // dark pass and the live pass must both start from the shipped default.
  await page.getByRole("button", { name: "Privacy", exact: true }).first().click();
  const shieldOn = page.getByRole("switch", { name: "Turn on the PII Shield" });
  const shieldOff = page.getByRole("switch", { name: "Turn off the PII Shield" });
  await shieldOn.or(shieldOff).first().waitFor({ timeout: 20000 });
  if (await shieldOn.isVisible().catch(() => false)) await shieldOn.click();
  await page.getByText("Personal data tokenized", { exact: true }).waitFor({ timeout: 20000 });
  // The vault line only renders once the status round-trip lands. It is
  // non-zero because protectDemoSession ran before any page opened.
  await page.getByText(/^Vault: [1-9]/).waitFor({ timeout: 20000 });
  await page.waitForTimeout(600);
  await shot("admin-privacy", "PII Shield on, coverage list reporting");

  // The scratch box: a sentence in, the tokens a model would actually receive
  // out, and the legend naming what each token stands for and how it was
  // found. This is the claim made checkable, so it is the crop the site uses.
  await page.getByRole("button", { name: /what it looks for and try a sentence/ }).click();
  const sample = page.locator("textarea").first();
  await sample.waitFor({ timeout: 20000 });
  await sample.fill(PII_SAMPLE);
  const runPreview = page.getByRole("button", { name: "Show what a model would see" });
  await runPreview.scrollIntoViewIfNeeded();
  await runPreview.click();
  // The result paragraph is the tokenized sentence; wait for a token in it.
  await page.getByText(/\[PERSON_1\]/).first().waitFor({ timeout: 30000 });
  await runPreview.scrollIntoViewIfNeeded();
  await page.waitForTimeout(700);
  await shot("admin-privacy-preview", "tokenized sample with its finding legend");

  await page.getByText("Offerings Catalog").first().click();
  const search = page.getByPlaceholder("Search offerings...");
  await search.waitFor({ timeout: 20000 });
  await page.locator("select").first().selectOption({ label: "Service Integrator" });
  await search.fill("Recovery");
  await page.getByText("Recovery Readiness Assessment", { exact: true }).waitFor();
  await shot("offerings-catalog", "three recovery services rendered");

  await page.getByText("Knowledge Sources").first().click();
  const source = page.getByText("Recovery Delivery Playbooks", { exact: true }).first();
  await source.waitFor({ timeout: 20000 });
  await source.click();
  await page.getByText("Recovery readiness pilot", { exact: true }).waitFor();
  await shot("knowledge-sources", "selected playbook collection with three records");

  // The redesigned setup screen: the action button pinned at the top with the
  // session's readiness line under it, and the steps below as collapsed cards
  // whose headers say what each one holds.
  await openSession(page, PRECALL_SESSION, "Not started");
  await page.getByRole("button", { name: /^Start Call$/ }).waitFor({ timeout: 20000 });
  await page.getByText(/participant/).first().waitFor({ timeout: 20000 });
  await page.waitForTimeout(700);
  await shot("precall-setup", "pre-call setup with a pinned action bar");

  await page.close();
}

async function runLive(colorScheme, suffix) {
  await api(`/sessions/${demo.id}`, {
    method: "PATCH",
    body: JSON.stringify({ state: "active" }),
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme });
  try {
    await page.goto(BASE, { waitUntil: "networkidle" });
    await page.evaluate(
      ({ key, messages, askKey, askModel }) => {
        sessionStorage.setItem(key, JSON.stringify(messages));
        localStorage.setItem(askKey, askModel);
      },
      {
        key: `backchannel:meeting-chat:${demo.id}`,
        messages: CHAT,
        askKey: `backchannel:ask-model:${demo.id}`,
        askModel: ASK_MODEL,
      },
    );
    await openSession(page, SESSION, "Live");
    const resume = page.getByRole("button", { name: "Resume Audio" });
    // The mic meter's caption: since ALP-305 the top bar suppresses its own
    // "Listening" status word on a healthy call, so the meter is the signal.
    const listening = page.getByText("Listening...", { exact: true }).first();
    await resume.or(listening).first().waitFor({ timeout: 20000 });
    if (await resume.isVisible().catch(() => false)) await resume.click();
    await listening.waitFor({ timeout: 20000 });
    await page.waitForTimeout(700);
    // Resuming to reach the live view appends a "Session Resumed" marker to
    // the transcript. That is real behavior, but it belongs to the capture
    // harness rather than the fictional call, so scroll it just out of frame
    // and let the panel show the conversation it is there to show.
    await page.evaluate(() => {
      const marker = [...document.querySelectorAll("div")].find(
        (el) => el.children.length === 0 && /Session Resumed/.test(el.textContent || ""),
      );
      if (!marker) return;
      let box = marker.parentElement;
      while (box && box.scrollHeight <= box.clientHeight + 1) box = box.parentElement;
      if (!box) return;
      box.scrollTop += marker.getBoundingClientRect().top - box.getBoundingClientRect().bottom;
    });
    await page.waitForTimeout(200);
    await page.screenshot({ path: `${OUT}/live-call${suffix}.png` });
    log.push(`  live-call${suffix} -- active call listening with saved insights and transcript`);

    // Filtered to objections: the handler's drafted responses are the densest
    // proof the live feed offers, and the unfiltered view leads with asks.
    await page.getByRole("button", { name: /^Objections/ }).first().click();
    await page.getByText(/not yet an approved supplier/i).first().waitFor({ timeout: 20000 });
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/live-objections${suffix}.png` });
    log.push(`  live-objections${suffix} -- objection cards with drafted responses`);

    // Filtered to questions: the newest card is the synthesizer's whole story
    // on one card - marked Answered, the answer summarized, and the follow-up
    // still owed spun off. Crop source for live-answered (FIG. 3). Type chips
    // combine, so clear the objections chip through All first.
    await page.getByRole("button", { name: /^All/ }).first().click();
    await page.waitForTimeout(400);
    await page.getByRole("button", { name: /^Questions/ }).first().click();
    await page.getByText(/Will isolated validation satisfy/i).first().waitFor({ timeout: 20000 });
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/live-questions${suffix}.png` });
    log.push(`  live-questions${suffix} -- answered question with its spun-off follow-up`);
    await page.getByRole("button", { name: /^All/ }).first().click();
    await page.waitForTimeout(400);

    // The command bar mid-question: typed, not submitted, so the shot stays
    // deterministic and never spends a provider call.
    const ask = page.getByPlaceholder("Ask this call anything...");
    await ask.waitFor({ timeout: 20000 });
    await ask.fill(ASK_DRAFT);
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${OUT}/live-ask${suffix}.png` });
    log.push(`  live-ask${suffix} -- question drafted in the call's command bar`);
  } finally {
    await page.close();
    await api(`/sessions/${demo.id}`, {
      method: "PATCH",
      body: JSON.stringify({ state: "completed" }),
    });
    await waitForAudioTeardown();
  }
}

// The PII Shield is a workspace-wide setting and the capture turns it on, so
// every pass has to hand it back off: a later pass that started with it on
// would lock the audio models and change shots that are not about privacy.
async function withShieldRestored(run) {
  try {
    await run();
  } finally {
    await api("/pii-shield", { method: "PUT", body: JSON.stringify({ enabled: false }) });
  }
}

const only = process.argv.includes("--light-only");

try {
  log.push("light:");
  await withShieldRestored(() => runCompleted("light", ""));
  if (!only) {
    log.push("dark:");
    await withShieldRestored(() => runCompleted("dark", "-dark"));
  }
  log.push("live:");
  await runLive("light", "");
  if (!only) await runLive("dark", "-dark");
} finally {
  await browser.close();
}

console.log(log.join("\n"));
console.log(`\ndone -> ${OUT}`);
