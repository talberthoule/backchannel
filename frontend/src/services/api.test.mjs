import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const sourcePath = fileURLToPath(new URL("./api.ts", import.meta.url));
const outputDir = await mkdtemp(join(tmpdir(), "api-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  entryPoints: [sourcePath],
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: outputPath,
});

const { getSynthesis } = createRequire(import.meta.url)(outputPath);

after(async () => {
  await rm(outputDir, { recursive: true, force: true });
});

test("signal history is requested only through an explicit opt-in", async () => {
  const urls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    urls.push(url);
    return { ok: true, status: 200, json: async () => null };
  };

  try {
    await getSynthesis("session-1", "live");
    await getSynthesis("session-1", "live", true);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(urls, [
    "/api/sessions/session-1/synthesis?mode=live&include_history=false",
    "/api/sessions/session-1/synthesis?mode=live&include_history=true",
  ]);
});
