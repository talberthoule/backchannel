// Captures Backchannel app screenshots for the product showcase.
// Usage: node showcase/capture.mjs   (app must be running at localhost:3000
// with the seeded "Fairview micro-seg strategy" session present)
// Playwright is reused from the product-showcase skill install.
import { createRequire } from "module";
import { homedir } from "os";
import { mkdirSync } from "fs";
import { join } from "path";

const require = createRequire(join(homedir(), ".claude/skills/product-showcase/bin/package.json"));
const { chromium } = require("playwright");

const OUT = "showcase/screenshots";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();

async function run(colorScheme, suffix) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, colorScheme });
  const shot = (name, opts = {}) => page.screenshot({ path: `${OUT}/${name}${suffix}.png`, ...opts });

  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });

  const expand = page.locator('[aria-label="Expand sidebar"]');
  if (await expand.isVisible()) await expand.click();

  await page.getByText("Fairview micro-seg strate").first().click();
  await page.waitForTimeout(600);

  // Briefing (default tab) - generate if empty, LLM call can take a while
  if (await page.getByText("No briefing has been generated").isVisible()) {
    await page.getByRole("button", { name: "Refresh Briefing" }).click();
    await page.getByText("No briefing has been generated").waitFor({ state: "hidden", timeout: 180000 });
    await page.waitForTimeout(800);
  }
  await shot("postcall-briefing");

  await page.getByRole("button", { name: /^Insights/ }).click();
  await page.waitForTimeout(600);
  await shot("postcall-insights");

  await page.getByRole("button", { name: /^Transcript/ }).click();
  await page.waitForTimeout(600);
  await shot("postcall-transcript");

  await page.getByRole("button", { name: /^Chat/ }).click();
  // handleSend silently no-ops until the model dropdown has loaded a value
  await page.waitForFunction(() => {
    const sels = [...document.querySelectorAll("select")];
    return sels.length > 0 && sels.every((s) => s.value);
  }, { timeout: 30000 });
  await page.getByPlaceholder("Ask about these meetings...").fill(
    "What did we commit to deliver for the client, and what are the next steps?"
  );
  await page.keyboard.press("Enter");
  await page.getByText("Thinking...").waitFor({ timeout: 10000 });
  await page.getByText("Thinking...").waitFor({ state: "hidden", timeout: 120000 });
  await page.waitForTimeout(500);
  await shot("postcall-chat");

  await page.getByText("Administration").first().click();
  await page.waitForTimeout(800);
  await shot("admin-agents");

  await page.close();
}

await run("light", "");
await run("dark", "-dark");

await browser.close();
console.log(`done -> ${OUT}`);
