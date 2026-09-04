import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const componentPath = fileURLToPath(new URL("./TranscriptionJobProgress.tsx", import.meta.url));
const outputDir = await mkdtemp(join(tmpdir(), "transcription-progress-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import TranscriptionJobProgress from "./TranscriptionJobProgress.tsx";
      export function render(job) {
        return renderToStaticMarkup(
          React.createElement(TranscriptionJobProgress, { job, onCancel: () => {} })
        );
      }
    `,
    resolveDir: dirname(componentPath),
    sourcefile: "transcription-progress-test-entry.tsx",
    loader: "tsx",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: outputPath,
});

const { render } = createRequire(import.meta.url)(outputPath);

after(async () => {
  await rm(outputDir, { recursive: true, force: true });
});

test("a running transcription reports model, segments, entries, and cancellation", () => {
  const markup = render({
    job_id: "job-1",
    kind: "retranscription",
    status: "running",
    model_id: "local-whisper-base",
    segments_done: 1,
    total_segments: 3,
    entries: 12,
    progress: 33,
    filename: null,
    error: "",
  });

  assert.match(markup, /Re-transcribing with/);
  assert.match(markup, /local-whisper-base/);
  assert.match(markup, /1 of 3 recordings/);
  assert.match(markup, /12 transcript entries/);
  assert.match(markup, /<progress[^>]+value="33"[^>]+max="100"/);
  assert.match(markup, /<button[^>]+type="button"[^>]*>Cancel<\/button>/);
  assert.match(markup, /role="status"/);
});

test("both entry points use the observable job flow", async () => {
  for (const relative of ["./PostCall/CallAudioPanel.tsx", "./PreCall/TranscriptImport.tsx"]) {
    const source = await readFile(fileURLToPath(new URL(relative, import.meta.url)), "utf8");
    assert.match(source, /waitForTranscriptionJob/);
    assert.match(source, /TranscriptionJobProgress/);
    assert.match(source, /cancelTranscriptionJob/);
  }
});
