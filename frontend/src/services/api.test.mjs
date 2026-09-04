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

const {
  cancelTranscriptionJob,
  getSynthesis,
  waitForTranscriptionJob,
} = createRequire(import.meta.url)(outputPath);

after(async () => {
  await rm(outputDir, { recursive: true, force: true });
});

// The client passes the opt-in through verbatim. The live call view gets its
// signals as insight rows instead (ALP-308); the post-call history panel is
// what asks for the raw rows.
test("the synthesis request carries the history opt-in it was given", async () => {
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

test("transcription jobs poll by kind until the terminal result", async () => {
  const urls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    urls.push(url);
    return {
      ok: true,
      status: 200,
      json: async () => ({
        job_id: "job-1",
        kind: "retranscription",
        status: urls.length === 1 ? "running" : "completed",
        model_id: "model-1",
        segments_done: urls.length,
        total_segments: 2,
        entries: 12,
        progress: urls.length * 50,
        filename: null,
        error: "",
      }),
    };
  };

  try {
    const result = await waitForTranscriptionJob(
      "session-1",
      {
        job_id: "job-1",
        kind: "retranscription",
        status: "queued",
        model_id: "model-1",
        segments_done: 0,
        total_segments: 2,
        entries: 0,
        progress: 0,
        filename: null,
        error: "",
      },
      () => {},
      0,
    );
    assert.equal(result.status, "completed");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(urls, [
    "/api/sessions/session-1/retranscribe",
    "/api/sessions/session-1/retranscribe",
  ]);
});

test("audio import cancellation uses the import job endpoint", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push([url, options?.method]);
    return {
      ok: true,
      status: 200,
      json: async () => ({ status: "canceling" }),
    };
  };

  try {
    await cancelTranscriptionJob("session-1", "audio_import");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(calls, [["/api/sessions/session-1/import/audio", "DELETE"]]);
});
