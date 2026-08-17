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
      import SynthesisSignals, { getRankedSignalCards, getPanelSignalIdentities } from "./SynthesisSignals.tsx";
      import BriefingView from "../PostCall/BriefingView.tsx";
      export { getRankedSignalCards, getPanelSignalIdentities };
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

const { renderLive, renderPost, getRankedSignalCards, getPanelSignalIdentities } =
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
  // The remaining two are captured, not panelled: the backend files them as
  // ordinary insight rows, which the list shows under Strategic.
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

test("the model's own ranking decides the panel, not section order", () => {
  // Section order alone would seat Signal, Risk and Discovery. The model ranks
  // the Action Cue and the Opportunity above two of them, so they take the seats.
  const ranked = getRankedSignalCards({
    ...liveSynthesis,
    strategic_signals: [{ title: "Routine signal", priority: 4 }],
    risks_blockers: [{ title: "Decisive risk", priority: 1 }],
    unresolved_discovery_questions: [{ title: "Nice-to-know question", priority: 5 }],
    top_opportunities: [{ title: "Live opportunity", priority: 3 }],
    action_plan: [{ title: "Do this now", priority: 2 }],
  });

  assert.deepEqual(
    ranked.map((card) => card.item.title),
    ["Decisive risk", "Do this now", "Live opportunity", "Routine signal", "Nice-to-know question"],
  );
});

test("an unranked signal sorts behind every ranked one, not ahead of rank 1", () => {
  const ranked = getRankedSignalCards({
    ...liveSynthesis,
    // No priority at all: the model did not rank it.
    strategic_signals: [{ title: "Unranked signal" }],
    risks_blockers: [{ title: "Ranked risk", priority: 2 }],
    unresolved_discovery_questions: [],
    top_opportunities: [],
    action_plan: [],
  });

  assert.deepEqual(
    ranked.map((card) => card.item.title),
    ["Ranked risk", "Unranked signal"],
  );
});

test("the panel identities are the top three, normalized for the insight list", () => {
  const identities = getPanelSignalIdentities({
    ...liveSynthesis,
    strategic_signals: [
      { title: "Budget owner changed.", priority: 1 },
      { title: "Fourth signal", priority: 4 },
    ],
    risks_blockers: [{ title: "Security review is the gate", priority: 2 }],
    unresolved_discovery_questions: [{ title: "Who chairs the board?", priority: 3 }],
    top_opportunities: [],
    action_plan: [],
  });

  // Trailing punctuation and case are stripped so these match the insight rows
  // the backend filed under the same identity.
  assert.deepEqual(
    [...identities].sort(),
    ["budget owner changed", "security review is the gate", "who chairs the board"],
  );
  assert.equal(identities.size, 3);
});

test("a post-call synthesis has no live panel and no panel identities", () => {
  const postCall = { ...liveSynthesis, mode: "post_call" };
  assert.deepEqual(getRankedSignalCards(postCall), []);
  assert.equal(getPanelSignalIdentities(postCall).size, 0);
  assert.deepEqual(getRankedSignalCards(null), []);
});

test("post-call briefing exposes the durable history even without a generated briefing", () => {
  const html = renderPost(session, 2);

  assert.match(html, /Strategic Signal History/);
  assert.match(html, /History \(2\)/);
});
