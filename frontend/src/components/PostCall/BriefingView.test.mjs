import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const componentPath = fileURLToPath(new URL("./BriefingView.tsx", import.meta.url));
const outputDir = await mkdtemp(join(tmpdir(), "briefing-view-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import BriefingView, {
        DIVIDED_LIST_CLASS,
        SectionHeading,
        StatusText,
        formatList,
        meetingTypeLabel,
        presentItems,
        sectionLabels,
        statusTone,
      } from "./BriefingView.tsx";
      import { ACTION_RISK_COLS, EVEN_COLS, buildBriefingLayout } from "./briefingSections.ts";
      export { ACTION_RISK_COLS, DIVIDED_LIST_CLASS, EVEN_COLS, buildBriefingLayout, formatList, meetingTypeLabel, presentItems, sectionLabels, statusTone };
      export function render(props) {
        return renderToStaticMarkup(React.createElement(BriefingView, props));
      }
      export function renderStatus(status) {
        return renderToStaticMarkup(React.createElement(StatusText, { status }));
      }
      export function renderHeading(props) {
        return renderToStaticMarkup(React.createElement(SectionHeading, props));
      }
    `,
    resolveDir: dirname(componentPath),
    sourcefile: "briefing-view-test-entry.tsx",
    loader: "tsx",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: outputPath,
});

const {
  render,
  renderStatus,
  renderHeading,
  ACTION_RISK_COLS,
  DIVIDED_LIST_CLASS,
  EVEN_COLS,
  buildBriefingLayout,
  formatList,
  meetingTypeLabel,
  presentItems,
  sectionLabels,
  statusTone,
} = createRequire(import.meta.url)(outputPath);

after(async () => {
  await rm(outputDir, { recursive: true, force: true });
});

const item = (title, extra = {}) => ({ title, summary: `${title} summary`, rationale: `${title} reason`, ...extra });

function synthesis(overrides = {}) {
  return {
    id: "synthesis-1",
    session_id: "session-1",
    mode: "post_call",
    status: "completed",
    top_outcomes: [],
    client_objectives: [],
    top_opportunities: [],
    risks_blockers: [],
    action_plan: [],
    unresolved_discovery_questions: [],
    strategic_signals: [],
    signal_history_count: 0,
    evidence_refs: [],
    lens_meeting: {},
    lens_discovery: {},
    arbiter_notes: "",
    model_ids: {},
    error_message: "",
    created_at: "2026-09-01T20:40:00Z",
    updated_at: null,
    clusters: [],
    ...overrides,
  };
}

function renderBriefing(overrides = {}, session = { id: "session-1", meeting_type: "general" }) {
  return render({
    session,
    synthesis: synthesis(overrides),
    signalHistoryCount: 0,
    onRefresh: async () => {},
    refreshing: false,
  });
}

test("statuses are quiet unless they ask for attention", () => {
  assert.equal(statusTone("Blocked"), "blocked");
  assert.equal(statusTone("At risk"), "blocked");
  assert.equal(statusTone("Open"), "open");
  assert.equal(statusTone("Pending"), "open");
  assert.equal(statusTone("Completed"), "quiet");
  assert.equal(statusTone("In progress"), "quiet");
  assert.equal(statusTone("Won"), "quiet");
});

test("only actionable statuses carry a mark", () => {
  const markup = renderBriefing({
    action_plan: [
      item("Blocked work", { status: "Blocked", owner: "Ana" }),
      item("Open work", { status: "Open", owner: "Ben" }),
      item("Finished work", { status: "Completed", owner: "Cy" }),
    ],
  });
  assert.equal(markup.match(/h-1\.5 w-1\.5 shrink-0 rounded-full bg-red-500/g)?.length, 1);
  assert.equal(markup.match(/h-1\.5 w-1\.5 shrink-0 rounded-full bg-brand-amber/g)?.length, 1);
  const finished = markup.slice(markup.indexOf("Finished work"), markup.indexOf("Cy"));
  assert.doesNotMatch(finished, /rounded-full/);
  assert.match(finished, /Completed/);
});

test("empty sections are omitted and named once in the footer", () => {
  const markup = renderBriefing({ action_plan: [item("Send the proposal")] });
  assert.doesNotMatch(markup, /border-dashed/);
  assert.doesNotMatch(markup, /Not captured in this briefing\.<\/p>/);
  assert.match(markup, /Action plan<\/h3><span[^>]*>1<\/span>/);
  assert.doesNotMatch(markup, /Risks and blockers<\/h3>/);
  assert.match(
    markup,
    /Not captured in this briefing: top outcomes, risks and blockers, objectives, top opportunities, and open questions\./,
  );
});

test("a briefing with nothing in it says so in one line", () => {
  const markup = renderBriefing({ status: "pending" });
  assert.match(markup, /Nothing was captured in this briefing yet\./);
  assert.doesNotMatch(markup, /Not captured in this briefing:/);
  assert.match(markup, /Briefing in progress/);
});

test("sections pair up only when both sides have content", () => {
  const pairCols = "lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]";
  const both = renderBriefing({ action_plan: [item("Do")], risks_blockers: [item("Risk")] });
  assert.ok(both.includes(pairCols));
  const lone = renderBriefing({ action_plan: [item("Do")] });
  assert.ok(!lone.includes(pairCols));
  assert.match(lone, /Action plan<\/h3>/);
});

test("top outcomes lead with hanging numerals and display type", () => {
  const markup = renderBriefing({ top_outcomes: [item("First"), item("Second")] });
  assert.match(markup, /Top outcomes<\/h3><span[^>]*>2<\/span>/);
  assert.match(markup, /<ol[^>]*><li[^>]*><span class="bc-accent-text[^"]*">1<\/span>/);
  assert.doesNotMatch(markup, /text-brand-teal[^"]*">1<\/span>/);
  assert.match(markup, /font-display text-lg font-semibold leading-snug tracking-tight[^>]*>First</);
});

test("the header names the meeting type and freshness, and the sections follow the meeting type", () => {
  const markup = renderBriefing({}, { id: "session-1", meeting_type: "client_sales" });
  assert.match(markup, /Client sales/);
  assert.match(markup, /Updated /);
  assert.equal(sectionLabels({ meeting_type: "client_sales" }).objectives, "Client objectives");
  assert.equal(meetingTypeLabel("internal_checkin"), "Internal check-in");
  assert.equal(meetingTypeLabel("something_new"), "something new");
});

test("rationale is closed by default behind one affordance with a real hit area", () => {
  const markup = renderBriefing({ action_plan: [item("Follow up")] });
  assert.match(markup, /Follow up summary<\/p><div class="mt-1\.5"><button[^>]*aria-expanded="false"/);
  assert.doesNotMatch(markup, /Follow up reason/);
  const button = markup.slice(markup.indexOf("<button", markup.indexOf("Follow up summary")), markup.indexOf("Why this matters"));
  assert.match(button, /min-h-8/);
  assert.match(button, /\[@media\(hover:none\)\]:min-h-11/);
  assert.match(button, /-my-2/);
});

test("items with nothing to read are skipped and never counted", () => {
  const blank = { title: "", summary: "  ", rationale: "orphaned reason", owner: "Nobody" };
  const markup = renderBriefing({
    action_plan: [item("Real work"), blank],
    risks_blockers: [blank],
    top_outcomes: [{ title: "", summary: "Summary only outcome" }],
  });
  assert.match(markup, /Action plan<\/h3><span[^>]*>1<\/span>/);
  assert.doesNotMatch(markup, /Nobody/);
  assert.doesNotMatch(markup, /orphaned reason/);
  assert.doesNotMatch(markup, /Risks and blockers<\/h3>/);
  assert.match(markup, /Not captured in this briefing: risks and blockers/);
  assert.match(markup, /Top outcomes<\/h3><span[^>]*>1<\/span>/);
  assert.match(markup, /Summary only outcome/);
  assert.equal(presentItems([blank, { title: "x", summary: "" }]).length, 1);
  assert.deepEqual(presentItems(undefined), []);
});

test("the status and heading pieces the Overview reuses keep their shape", () => {
  assert.match(renderStatus("Blocked"), /^<span class="inline-flex items-center gap-1\.5 [^"]*text-red-700[^"]*"><span aria-hidden="true" class="[^"]*bg-red-500"><\/span>Blocked<\/span>$/);
  assert.equal(renderStatus("Done"), "<span>Done</span>");
  const heading = renderHeading({ label: "Action plan", count: 4 });
  assert.match(heading, /<h3 class="font-display text-\[11px\] font-semibold uppercase tracking-\[0\.12em\] text-brand-mid-gray">Action plan<\/h3>/);
  assert.match(heading, /tabular-nums[^>]*>4<\/span>/);
  assert.doesNotMatch(renderHeading({ label: "Empty", count: 0 }), /<span/);
  assert.match(renderHeading({ label: "Named", id: "overview-named" }), /<h3 id="overview-named" class="/);
  assert.equal(DIVIDED_LIST_CLASS, "divide-y divide-brand-light-gray-1/60");
});

test("without a briefing the page offers to generate one and keeps the signal history", () => {
  const markup = render({
    session: { id: "session-1", meeting_type: "general" },
    synthesis: null,
    signalHistoryCount: 3,
    onRefresh: async () => {},
    refreshing: false,
  });
  assert.match(markup, /Generate Briefing/);
  assert.match(markup, /bg-brand-teal font-semibold text-white/);
  assert.match(markup, /No briefing generated yet/);
  assert.match(markup, /No briefing was generated for this call/);
  assert.match(markup, /Strategic signal history<\/h3><span[^>]*>3<\/span>/);
  assert.match(markup, /History \(3\)/);
  assert.doesNotMatch(markup, /Top outcomes/);
});

test("an existing briefing gets a quiet refresh control and surfaces errors", () => {
  const markup = render({
    session: { id: "session-1", meeting_type: "general" },
    synthesis: synthesis({ status: "error", error_message: "Model timed out" }),
    signalHistoryCount: 0,
    onRefresh: async () => {},
    refreshing: false,
    error: "Refresh failed",
  });
  assert.match(markup, /Refresh Briefing/);
  assert.doesNotMatch(markup, /bg-brand-teal font-semibold text-white/);
  assert.match(markup, /Briefing failed/);
  assert.equal(markup.match(/role="alert"/g)?.length, 2);
  assert.match(markup, /Refresh failed/);
  assert.match(markup, /Model timed out/);
});

test("the layout helper pairs sections only when both have content and drops empties", () => {
  const session = { meeting_type: "general" };
  const both = buildBriefingLayout(session, synthesis({ action_plan: [item("Do")], risks_blockers: [item("Risk")] }));
  assert.deepEqual(
    both.blocks.map((block) => [block.kind, block.kind === "pair" ? block.sections.map((s) => s.key) : block.section.key]),
    [["pair", ["actions", "risks"]]],
  );
  assert.equal(both.blocks[0].cols, ACTION_RISK_COLS);
  assert.equal(both.missingNote, "Not captured in this briefing: top outcomes, objectives, top opportunities, and open questions.");

  const lone = buildBriefingLayout(session, synthesis({ risks_blockers: [item("Risk")], top_opportunities: [item("Win")] }));
  assert.deepEqual(
    lone.blocks.map((block) => [block.kind, block.section.key]),
    [["single", "risks"], ["single", "opportunities"]],
  );

  const full = buildBriefingLayout(
    session,
    synthesis({
      top_outcomes: [item("Outcome")],
      action_plan: [item("Do")],
      risks_blockers: [item("Risk")],
      client_objectives: [item("Goal")],
      top_opportunities: [item("Win")],
      unresolved_discovery_questions: [item("Ask")],
      strategic_signals: [item("Signal")],
    }),
  );
  assert.deepEqual(full.blocks.map((block) => block.kind), ["lead", "pair", "pair", "single", "single"]);
  assert.equal(full.blocks[2].cols, EVEN_COLS);
  assert.equal(full.blocks[4].section.label, "Strategic signals");
  assert.equal(full.missingNote, null);

  assert.deepEqual(buildBriefingLayout(session, synthesis()), { blocks: [], missingNote: "Nothing was captured in this briefing yet." });
  assert.deepEqual(buildBriefingLayout(session, null), { blocks: [], missingNote: null });
});

test("the layout helper follows the meeting type and counts only readable items", () => {
  const layout = buildBriefingLayout(
    { meeting_type: "client_sales" },
    synthesis({
      client_objectives: [item("Goal"), { title: " ", summary: "" }],
      unresolved_discovery_questions: [{ title: "", summary: "Budget owner?" }],
    }),
  );
  const objectives = layout.blocks.find((block) => block.kind === "single" && block.section.key === "objectives").section;
  assert.equal(objectives.label, "Client objectives");
  assert.equal(objectives.items.length, 1);
  const questions = layout.blocks.find((block) => block.kind === "single" && block.section.key === "questions").section;
  assert.equal(questions.label, "Unresolved discovery questions");
  assert.deepEqual(questions.items, [{ title: "", summary: "Budget owner?" }]);
  assert.equal(layout.missingNote, "Not captured in this briefing: top outcomes, action plan, risks and blockers, and top opportunities.");
});

test("formatList reads as prose", () => {
  assert.equal(formatList([]), "");
  assert.equal(formatList(["a"]), "a");
  assert.equal(formatList(["a", "b"]), "a and b");
  assert.equal(formatList(["a", "b", "c"]), "a, b, and c");
});
