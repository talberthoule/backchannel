// Renders the social share card served at site/assets/og-image.png.
//
// Usage:  node showcase/og_card.mjs            (after showcase/capture.mjs)
//         node showcase/og_card.mjs --out PATH
//
// The card is the most-seen image the project has: every link preview on
// Slack, LinkedIn, and X renders it. The first one was hand-composed around a
// screenshot from the retired `user-*` family -- a real customer call -- and so
// could neither be regenerated nor safely kept. This builds it from the same
// fictional Alderwake capture as every other public asset, through the browser
// that already renders the site, so the type and color are the site's own.
//
// Everything is inlined as a data URI, so the page has no origin and needs no
// file access.
import { createRequire } from "module";
import { homedir } from "os";
import { readFileSync } from "fs";
import { join } from "path";

const require = createRequire(join(homedir(), ".claude/skills/product-showcase/bin/package.json"));
const { chromium } = require("playwright");

const outArg = process.argv.indexOf("--out");
const OUT = outArg > -1 ? process.argv[outArg + 1] : "site/assets/og-image.png";
const SHOT = "showcase/screenshots/live-call-dark.png";
const WORDMARK = "site/assets/wordmark.svg";

const dataUri = (path, mime) => `data:${mime};base64,${readFileSync(path).toString("base64")}`;

const html = `
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    width: 1200px; height: 630px; overflow: hidden; position: relative;
    background: #0c1413;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    color: #e4ecea;
  }
  /* The same teal the product uses for a live agent, bled behind the shot. */
  .glow {
    position: absolute; right: -180px; top: -220px; width: 900px; height: 900px;
    background: radial-gradient(circle, rgba(45, 212, 191, 0.20) 0%, rgba(45, 212, 191, 0) 62%);
  }
  .copy { position: absolute; left: 64px; top: 64px; width: 530px; }
  .wordmark { width: 300px; display: block; }
  h1 {
    margin-top: 40px; font-size: 46px; line-height: 1.12; letter-spacing: -0.02em;
    font-weight: 700;
  }
  h1 span { color: #2dd4bf; display: block; }
  p.lede {
    margin-top: 22px; font-size: 21px; line-height: 1.45; color: #a9bcb7;
  }
  .foot {
    position: absolute; left: 64px; bottom: 56px; font-size: 19px; color: #8ba39e;
  }
  .foot b { color: #2dd4bf; font-weight: 600; }
  /* The shot bleeds off the right edge: a window onto the product, not a
     floating rectangle. Scaled so the live insight card stays legible at the
     ~600px width most timelines actually render. */
  .shot {
    position: absolute; right: -56px; top: 104px; width: 640px; height: 430px;
    border: 1px solid #223330; border-radius: 14px; overflow: hidden;
    box-shadow: 0 30px 70px rgba(0, 0, 0, 0.55);
  }
  /* Sidebar cropped away by the negative margin: the card has room for the
     call, not for navigation. */
  .shot img { width: 900px; display: block; margin: -58px 0 0 -160px; }
</style>
<div class="glow"></div>
<div class="copy">
  <img class="wordmark" src="${dataUri(WORDMARK, "image/svg+xml")}" alt="Backchannel" />
  <h1>Your meetings, transcribed live.<br />Your next move, <span>surfaced mid-call.</span></h1>
  <p class="lede">Self-hosted, open-source AI meeting assistant. No bot in the call, and with the PII Shield on, no name in any prompt.</p>
</div>
<div class="foot"><b>backchannel.page</b> &nbsp;&middot;&nbsp; MIT licensed &nbsp;&middot;&nbsp; open source</div>
<div class="shot"><img src="${dataUri(SHOT, "image/png")}" alt="" /></div>
`;

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1200, height: 630 },
  colorScheme: "dark",
  deviceScaleFactor: 1,
});
await page.setContent(html);
await page.waitForTimeout(400);
await page.screenshot({ path: OUT });
await browser.close();
console.log(`og card -> ${OUT}`);
