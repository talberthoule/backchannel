import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const componentDir = dirname(fileURLToPath(new URL("./ActiveCall/SynthesisSignals.tsx", import.meta.url)));
const outputDir = await mkdtemp(join(tmpdir(), "signal-history-view-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import SynthesisSignals from "./SynthesisSignals.tsx";
      import BriefingView from "../PostCall/BriefingView.tsx";
      export function renderLive(session, synthesis) {
        return renderToStaticMarkup(React.createElement(SynthesisSignals, { session, synthesis }));
      }
      export function renderPost(session, signalHistoryCount) {
        return renderToStaticMarkup(React.createElement(BriefingView, {
          session,
          synthesis: null,
          signalHistoryCount,
          refreshing: false,
          onRefresh: async () => {},
        }));
      }
    `,
    resolveDir: componentDir,
    sourcefile: "signal-history-view-test-entry.tsx",
    loader: "tsx",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: outputPath,
});

const { renderLive, renderPost } = createRequire(import.meta.url)(outputPath);

after(async () => {
  await rm(outputDir, { recursive: true, force: true });
});

const session = {
  id: "session-1",
  meeting_type: "general",
  meeting_context: "",
};

const liveSynthesis = {
  mode: "live",
  status: "completed",
  strategic_signals: [{ title: "Current budget signal", summary: "Current cycle" }],
  top_outcomes: [],
  top_opportunities: [],
  risks_blockers: [],
  action_plan: [],
  unresolved_discovery_questions: [],
  signal_history: [],
  signal_history_count: 2,
  clusters: [],
};

test("live cards stay primary while accumulated history is available on demand", () => {
  const html = renderLive(session, liveSynthesis);

  assert.match(html, /Current budget signal/);
  assert.match(html, /History \(2\)/);
  assert.match(html, /aria-expanded="false"/);
  assert.doesNotMatch(html, /Earlier budget signal/);
});

test("post-call briefing exposes the durable history even without a generated briefing", () => {
  const html = renderPost(session, 2);

  assert.match(html, /Strategic Signal History/);
  assert.match(html, /History \(2\)/);
});
