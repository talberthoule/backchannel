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
      import SynthesisSignals, { getStrategicSignalItems } from "./SynthesisSignals.tsx";
      import BriefingView from "../PostCall/BriefingView.tsx";
      export { getStrategicSignalItems };
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

const { renderLive, renderPost, getStrategicSignalItems } =
  createRequire(import.meta.url)(outputPath);

after(async () => {
  await rm(outputDir, { recursive: true, force: true });
});

const session = {
  id: "session-1",
  meeting_type: "general",
  meeting_context: "",
};

const item = (title) => ({ title, summary: `${title} detail` });

const liveSynthesis = {
  mode: "live",
  status: "completed",
  strategic_signals: [item("Current budget signal")],
  top_outcomes: [item("Outcome signal")],
  top_opportunities: [item("Opportunity signal")],
  risks_blockers: [item("Risk signal")],
  action_plan: [item("Action cue signal")],
  unresolved_discovery_questions: [item("Discovery signal")],
  signal_history: [],
  signal_history_count: 2,
  clusters: [],
};

test("the live panel shows the top three signals and nothing past them", () => {
  const html = renderLive(session, liveSynthesis);

  // Signal, Risk and Next Question, in that priority order.
  assert.match(html, /Current budget signal/);
  assert.match(html, /Risk signal/);
  assert.match(html, /Discovery signal/);
  // The remaining two are captured, not panelled: they live under the insight
  // list's Strategic filter instead.
  assert.doesNotMatch(html, /Opportunity signal/);
  assert.doesNotMatch(html, /Action cue signal/);
});

test("the live panel no longer carries its own history container", () => {
  const html = renderLive(session, liveSynthesis);

  assert.doesNotMatch(html, /History \(/);
  assert.doesNotMatch(html, /Hide history/);
});

test("the live panel disappears entirely when no signal has been produced", () => {
  const html = renderLive(session, {
    ...liveSynthesis,
    strategic_signals: [],
    top_outcomes: [],
    top_opportunities: [],
    risks_blockers: [],
    action_plan: [],
    unresolved_discovery_questions: [],
  });

  assert.equal(html, "");
});

test("the captured set carries every signal, newest first, counted once", () => {
  const items = getStrategicSignalItems({
    ...liveSynthesis,
    // The agent is still emitting a signal that history already knows about,
    // alongside one history has not merged yet.
    strategic_signals: [{ title: "Budget owner changed." }, { title: "Brand new signal" }],
    updated_at: "2026-08-16T10:10:00Z",
    signal_history: [
      {
        section: "strategic_signals",
        title: "Budget owner changed",
        summary: "",
        first_seen: "2026-08-16T09:00:00Z",
        last_seen: "2026-08-16T10:05:00Z",
        count: 4,
      },
      {
        section: "risks_blockers",
        title: "Security review is the gate",
        summary: "",
        first_seen: "2026-08-16T09:30:00Z",
        last_seen: "2026-08-16T09:30:00Z",
        count: 1,
      },
    ],
  });

  assert.deepEqual(
    items.map((entry) => entry.title),
    ["Brand new signal", "Budget owner changed", "Security review is the gate"],
  );
  // Trailing punctuation and case must not split a signal from its history:
  // the merged entry keeps its first_seen and its seen count.
  assert.equal(items[1].count, 4);
  assert.equal(items[1].first_seen, "2026-08-16T09:00:00Z");
});

test("the captured set is empty for a post-call synthesis", () => {
  assert.deepEqual(getStrategicSignalItems({ ...liveSynthesis, mode: "post_call" }), []);
  assert.deepEqual(getStrategicSignalItems(null), []);
});

test("post-call briefing exposes the durable history even without a generated briefing", () => {
  const html = renderPost(session, 2);

  assert.match(html, /Strategic Signal History/);
  assert.match(html, /History \(2\)/);
});
