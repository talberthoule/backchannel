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
      import OverviewView from "./OverviewView.tsx";
      export function render(props) {
        return renderToStaticMarkup(React.createElement(PostCallView, props));
      }
      export function renderBriefing(props) {
        return renderToStaticMarkup(React.createElement(BriefingView, props));
      }
      export function renderOverview(props) {
        return renderToStaticMarkup(React.createElement(OverviewView, props));
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

const { render, renderBriefing, renderOverview } = createRequire(import.meta.url)(outputPath);

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
  const owner = "Maya Chen";
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

  assert.equal(2, markup.match(new RegExp(owner, "g"))?.length);
  for (const [title, status, summary] of [
    ["Hero title", "Completed", "Hero summary"],
    ["Section title", "Pending", "Section summary"],
  ]) {
    const titleAt = markup.indexOf(title);
    const item = markup.slice(markup.lastIndexOf("<li", titleAt), markup.indexOf("</li>", titleAt));
    assert.ok(item.indexOf(title) < item.indexOf(status) && item.indexOf(status) < item.indexOf(owner) && item.indexOf(owner) < item.indexOf(summary), `${status} and owner should share the title row`);
    assert.match(item, new RegExp(`${summary}</p><div class="mt-1\\.5">`));
  }
});

// --- Overview worksheet ------------------------------------------------

const at = (minutes) => new Date(Date.UTC(2026, 8, 1, 20, minutes)).toISOString();

const overviewSession = {
  id: "session-2",
  name: "Discovery with Patrick",
  state: "completed",
  created_at: at(0),
  started_at: at(0),
  ended_at: at(34),
  notes: null,
  meeting_type: "client_sales",
  meeting_context: "",
  group_id: null,
  speaker_context_dirty: false,
  speaker_context_enhanced_at: null,
  drain_summary: "",
};

const insight = (id, item_type, question, extra = {}) => ({
  id,
  session_id: "session-2",
  item_type,
  question,
  rationale: `${question} rationale`,
  source_context: "",
  directive_id: null,
  starred: false,
  dismissed: false,
  created_at: at(6),
  answered: false,
  answer_summary: "",
  needs_followup: false,
  followup_question: "",
  ...extra,
});

const overviewQuestions = () => [
  ...Array.from({ length: 8 }, (_, i) => insight(`a-${i}`, "action_item", `Commitment ${i}`)),
  insight("q-1", "question", "What is the budget ceiling?"),
  insight("q-2", "question", "Who owns the rollout?", { answered: true }),
  insight("p-1", "opportunity", "Digital twin showcase", { offering_match: "Twin" }),
  insight("s-1", "signal", "Engineering defensiveness", { lens_label: "Risk" }),
  insight("s-2", "signal", "Remind Patrick on positioning", { lens_label: "Action Cue" }),
];

const overviewSynthesis = () => ({
  id: "syn-2",
  session_id: "session-2",
  mode: "post_call",
  status: "completed",
  top_outcomes: [{ title: "Agreed on a Q4 pilot", summary: "Two sites over ninety days", rationale: "" }],
  client_objectives: [],
  top_opportunities: [],
  risks_blockers: [{ title: "Procurement freeze", summary: "Until the new fiscal year", owner: "Drew", status: "Blocked" }],
  action_plan: [
    { title: "Send the pricing deck", summary: "Rephrased by the arbiter", owner: "Maya", status: "Pending" },
    { title: "Loop in procurement", summary: "Before the SOW", owner: "Drew" },
  ],
  unresolved_discovery_questions: [],
  strategic_signals: [],
  signal_history_count: 0,
  evidence_refs: [],
  lens_meeting: {},
  lens_discovery: {},
  arbiter_notes: "",
  model_ids: {},
  error_message: "",
  created_at: at(35),
  updated_at: null,
  clusters: [],
});

const overviewProps = (overrides = {}) => ({
  session: overviewSession,
  questions: overviewQuestions(),
  transcripts: [
    { text: "one two three four five six", timestamp: at(1), speaker_id: "sp-a" },
    { text: "seven eight", timestamp: at(2), speaker_id: "sp-b" },
  ],
  directives: [],
  documents: [],
  segments: [{ id: "seg-1", session_id: "session-2", segment_number: 1, started_at: at(0), ended_at: at(34) }],
  speakers: [
    { id: "sp-a", session_id: "session-2", name: "Patrick", role: "", color: "#123456", is_user: false, speaker_type: "external", display_name: "", display_name_enabled: false, created_at: at(0) },
    { id: "sp-b", session_id: "session-2", name: "Me", role: "", color: "#654321", is_user: true, speaker_type: "team", display_name: "", display_name_enabled: false, created_at: at(0) },
  ],
  synthesis: overviewSynthesis(),
  signalHistoryCount: 0,
  onResumeCall: noop,
  onDeleteSession: noop,
  onRefreshSpeakers: noop,
  onRefreshSession: noop,
  onRefreshQuestions: noop,
  onRefreshSynthesis: async () => {},
  onOpenAdminAgents: noop,
  onRenameSession: async () => {},
  ...overrides,
});

const tile = (markup, label) => {
  const match = markup.match(new RegExp(`${label}</p><p[^>]*>([^<]*)</p><p[^>]*>([^<]*)</p>`));
  assert.ok(match, `tile ${label} not found`);
  return { value: match[1], sub: match[2] };
};

test("the review tabs are a tablist with Overview selected first and Insights keeping its raw count", () => {
  const markup = render(overviewProps());

  assert.match(markup, /role="tablist" aria-label="Post-call review"/);
  const selected = [...markup.matchAll(/<button[^>]*role="tab"[^>]*aria-selected="true"[^>]*>([^<]*)/g)].map((m) => m[1].trim());
  assert.deepEqual(selected, ["Overview"]);
  // Roving tabindex: only the selected tab is in the Tab order.
  assert.equal((markup.match(/role="tab"[^>]*tabindex="0"/g) || []).length, 1);
  assert.equal((markup.match(/role="tab"[^>]*tabindex="-1"/g) || []).length, 8);
  assert.match(markup, /role="tabpanel" id="post-call-panel-overview" aria-labelledby="post-call-tab-overview"/);
  assert.match(markup, /Insights<span[^>]*>\(13\)<\/span>/);
  assert.ok(markup.indexOf(">Overview<") < markup.indexOf(">Briefing<"));
});

test("the Overview headline is the briefing's top outcome with only type and speakers as context", () => {
  const markup = render(overviewProps());

  assert.match(markup, /Agreed on a Q4 pilot/);
  assert.match(markup, /Two sites over ninety days/);
  assert.match(markup, /Top outcome from the briefing/);
  assert.match(markup, /Client sales/);
  assert.match(markup, /2 speakers/);
  // Date and duration already sit in the session card above the tabs.
  assert.doesNotMatch(markup, /34 min/);
});

test("with a briefing, tiles count briefing rows and each list says where the live rows live", () => {
  const markup = render(overviewProps());

  // Commitments: the two plan steps, not the eight live action items.
  assert.deepEqual(tile(markup, "Commitments"), { value: "2", sub: "From the briefing" });
  assert.match(markup, /Send the pricing deck/);
  assert.match(markup, /Loop in procurement/);
  assert.match(markup, /8 action items in Insights/);
  // Open loops: the briefing has none, so the live questions are the source.
  assert.deepEqual(tile(markup, "Open loops"), { value: "1", sub: "From Insights" });
  assert.match(markup, /What is the budget ceiling\?/);
  assert.doesNotMatch(markup, /Who owns the rollout\?/);
  assert.match(markup, /1 open of 2 questions in Insights/);
  // Opportunities: no briefing rows, so the live opportunity with its match.
  assert.deepEqual(tile(markup, "Opportunities"), { value: "1", sub: "From Insights" });
  assert.match(markup, /Digital twin showcase/);
  assert.match(markup, /Matched to an offering/);
  // Risks: the briefing blocker, with the live risk share of current signals.
  assert.deepEqual(tile(markup, "Risks"), { value: "1", sub: "From the briefing" });
  assert.match(markup, /Procurement freeze/);
  assert.match(markup, /1 of 2 current strategic signals in Insights/);
  assert.doesNotMatch(markup, /Engineering defensiveness/);
});

test("briefing statuses carry the Briefing's tone on Overview rows", () => {
  const markup = render(overviewProps());

  // "Blocked" renders through StatusText: a red mark beside the word.
  const blockedAt = markup.indexOf(">Blocked<");
  assert.ok(blockedAt > 0);
  const row = markup.slice(markup.lastIndexOf("<li", blockedAt), blockedAt);
  assert.match(row, /bg-red-500/);
  assert.match(row, /Procurement freeze/);
  // "Pending" is an open item: amber mark, quiet text.
  const pendingAt = markup.indexOf(">Pending<");
  assert.match(markup.slice(markup.lastIndexOf("<li", pendingAt), pendingAt), /bg-brand-amber/);
  assert.match(markup, /Maya/);
});

test("the lists share one sheet with small-caps headings instead of six boxed panels", () => {
  const markup = render(overviewProps());

  // Four list headings in the Briefing's small-caps style, none with an icon.
  const headings = markup.match(/<h3 class="font-display text-\[11px\] font-semibold uppercase tracking-\[0\.12em\] text-brand-mid-gray">(Commitments|Open loops|Opportunities|Risks)<\/h3>/g) || [];
  assert.equal(headings.length, 4);
  // Boxed treatment only for the two measured panels and the sheet itself
  // (the session card above the tabs is outside the panel).
  const panel = markup.slice(markup.indexOf('role="tabpanel"'));
  const boxes = panel.match(/rounded-xl bg-surface p(x-5 py-6|-5|-6) shadow-sm/g) || [];
  assert.equal(boxes.length, 4, "headline, list sheet, participation, rhythm");
  assert.match(markup, /aria-labelledby="overview-participation"/);
  assert.match(markup, /aria-labelledby="overview-rhythm"/);
  assert.match(markup, /Talk share by words: Patrick 75%, Me 25%/);
  assert.match(markup, /Busiest window 5-10 min with 13 insights/);
});

test("without a briefing, tiles count live insights, lists cap, and links say how many are in Insights", () => {
  const markup = render(overviewProps({ synthesis: null }));

  assert.deepEqual(tile(markup, "Commitments"), { value: "8", sub: "From Insights" });
  assert.match(markup, /Commitment 5/);
  assert.doesNotMatch(markup, /Commitment 6/);
  assert.match(markup, /8 action items in Insights/);
  assert.deepEqual(tile(markup, "Risks"), { value: "1", sub: "From Insights" });
  assert.match(markup, /Engineering defensiveness/);
  assert.doesNotMatch(markup, /Remind Patrick on positioning/);
  assert.match(markup, /Counts from the captured record/);
});

test("the cost tile shows the skeleton only while loading and says when usage is unavailable", () => {
  // The usage request starts at mount, so the first paint is the skeleton.
  const loading = render(overviewProps());
  assert.match(loading, /Est\. spend<\/p><p[^>]*><span[^>]*animate-pulse[^>]*><\/span><\/p><p[^>]*>Loading usage<\/p>/);

  const unavailable = renderOverview({
    ...overviewProps(),
    tokenUsage: null,
    tokenUsageLoading: false,
    tokenUsageError: true,
    modelPricing: null,
    onNavigate: noop,
  });
  assert.deepEqual(tile(unavailable, "Est. spend"), { value: "-", sub: "Usage unavailable" });
  assert.doesNotMatch(unavailable, /animate-pulse/);
});

test("an analysis error shows under the headline even once insights exist", () => {
  const markup = renderOverview({
    ...overviewProps(),
    tokenUsage: null,
    tokenUsageLoading: false,
    tokenUsageError: false,
    modelPricing: null,
    onNavigate: noop,
    analyzeError: "Analysis finished, but the briefing failed: quota exceeded",
  });

  assert.match(markup, /role="alert"[^>]*>Analysis finished, but the briefing failed: quota exceeded</);
  assert.ok(markup.indexOf("quota exceeded") < markup.indexOf(">Commitments</p>"));
});

test("a transcript with no analysis gets an Analyze nudge instead of empty lists", () => {
  const markup = render(overviewProps({ questions: [], synthesis: null }));

  assert.match(markup, /Nothing has been analyzed yet/);
  assert.match(markup, /Analyze transcript/);
  assert.doesNotMatch(markup, />Commitments</);
  assert.doesNotMatch(markup, /Est\. spend/);
  assert.match(markup, /Talk share by words/);
  assert.match(markup, /no briefing has been generated/);
});

test("a session whose insights were all dismissed is not offered Analyze again", () => {
  const markup = render(overviewProps({
    questions: overviewQuestions().map((q) => ({ ...q, dismissed: true })),
    synthesis: null,
  }));

  assert.doesNotMatch(markup, /Analyze transcript/);
  assert.doesNotMatch(markup, /Nothing has been analyzed yet/);
  assert.deepEqual(tile(markup, "Commitments").value, "0");
});

test("an empty session says so plainly without an Analyze button", () => {
  const markup = render(overviewProps({ questions: [], synthesis: null, transcripts: [], segments: [], session: { ...overviewSession, started_at: null, ended_at: null } }));

  assert.match(markup, /No transcript was recorded either/);
  assert.doesNotMatch(markup, /Analyze transcript/);
  assert.match(markup, /No transcript text to measure/);
});

test("completion notes use the accent tokens and announce as status; the export menu is a real menu", () => {
  const markup = render(overviewProps({
    postProcessing: { active: false, state: "completed", stage: "", message: "Post-processing complete", currentStep: 3, totalSteps: 3, progress: 1, startedAt: null, completedAt: null, confirmed: true },
  }));

  assert.match(markup, /role="status" class="rounded-lg border border-brand-teal\/30 bg-brand-teal\/10/);
  assert.doesNotMatch(markup, /bg-green-50/);
  assert.match(markup, /aria-haspopup="menu" aria-expanded="false" aria-controls="post-call-export-menu"/);
  assert.match(markup, /id="post-call-export-menu" role="menu"/);
  assert.equal((markup.match(/role="menuitem" tabindex="-1"/g) || []).length, 3);
  assert.match(markup, /transition-opacity/);
  assert.doesNotMatch(markup, /transition-all[^"]*z-10/);
});
