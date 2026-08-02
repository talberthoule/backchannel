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
      import BriefingView from "./BriefingView.tsx";
      export function render(props) {
        return renderToStaticMarkup(React.createElement(PostCallView, props));
      }
      export function renderBriefing(props) {
        return renderToStaticMarkup(React.createElement(BriefingView, props));
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

const { render, renderBriefing } = createRequire(import.meta.url)(outputPath);

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

test("briefing item metadata is safe and ordered in hero and section rows", () => {
  const owner = "e2f5633a-f9c2-4fad-b44e-db1a559525f1";
  const markup = renderBriefing({
    session: { id: "session-1", meeting_type: "general" },
    synthesis: {
      id: "synthesis-1",
      status: "completed",
      top_outcomes: [{ title: "Hero title", summary: "Hero summary", rationale: "Hero reason", owner, status: "Completed" }],
      action_plan: [{ title: "Section title", summary: "Section summary", rationale: "Section reason", owner, status: "Pending" }],
      risks_blockers: [],
      client_objectives: [],
      top_opportunities: [],
      unresolved_discovery_questions: [],
      strategic_signals: [],
      clusters: [],
      arbiter_notes: "",
    },
    signalHistoryCount: 0,
    onRefresh: async () => {},
    refreshing: false,
  });

  assert.doesNotMatch(markup, new RegExp(owner));
  for (const [title, status, summary] of [
    ["Hero title", "Completed", "Hero summary"],
    ["Section title", "Pending", "Section summary"],
  ]) {
    const titleAt = markup.indexOf(title);
    const item = markup.slice(markup.lastIndexOf("<li", titleAt), markup.indexOf("</li>", titleAt));
    assert.ok(item.indexOf(title) < item.indexOf(status) && item.indexOf(status) < item.indexOf(summary), `${status} should share the title row`);
    assert.match(item, new RegExp(`${summary}</p><div class="mt-1\\.5">`));
  }
});
