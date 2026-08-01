import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const componentPath = fileURLToPath(new URL("./PostCallView.tsx", import.meta.url));
const outputDir = await mkdtemp(join(tmpdir(), "post-call-view-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import PostCallView from "./PostCallView.tsx";
      export function render(props) {
        return renderToStaticMarkup(React.createElement(PostCallView, props));
      }
    `,
    resolveDir: dirname(componentPath),
    sourcefile: "post-call-view-test-entry.tsx",
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

const noop = () => {};

test("enhanced sessions offer one unified Insights Excel download", () => {
  const markup = render({
    session: {
      id: "session-1",
      name: "Client Review",
      state: "completed",
      created_at: "2026-08-01T00:00:00Z",
      started_at: "2026-08-01T00:00:00Z",
      ended_at: "2026-08-01T00:30:00Z",
      notes: null,
      meeting_type: "general",
      meeting_context: "",
      group_id: null,
      speaker_context_dirty: false,
      speaker_context_enhanced_at: "2026-08-01T00:31:00Z",
      speaker_context_version: 1,
      drain_summary: "",
    },
    questions: [],
    transcripts: [],
    directives: [],
    documents: [],
    segments: [],
    speakers: [],
    synthesis: null,
    onResumeCall: noop,
    onDeleteSession: noop,
    onRefreshSpeakers: noop,
    onRefreshSession: noop,
    onRefreshQuestions: noop,
    onRefreshSynthesis: async () => {},
    onRenameSession: async () => {},
  });
  const hrefs = [...markup.matchAll(/href="([^"]*questions-export[^"]*)"/g)]
    .map((match) => match[1]);

  assert.deepEqual(hrefs, ["/api/sessions/session-1/artifacts/questions-export"]);
  assert.doesNotMatch(markup, /Enhanced Insights \(Excel\)/);
});
