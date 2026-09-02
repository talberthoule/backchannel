import assert from "node:assert/strict";
import test from "node:test";

// The module carries only type imports, so Node's type stripping loads it as-is.
const load = () => import("./overviewMetrics.ts");

const at = (minutes) => new Date(Date.UTC(2026, 8, 1, 20, minutes)).toISOString();

const session = {
  id: "session-1",
  name: "Meeting",
  state: "completed",
  created_at: at(0),
  started_at: at(0),
  ended_at: at(34),
  notes: null,
  meeting_type: "general",
  meeting_context: "",
  group_id: null,
  speaker_context_dirty: false,
  speaker_context_enhanced_at: null,
};

const insight = (id, item_type, question, extra = {}) => ({
  id,
  session_id: "session-1",
  item_type,
  question,
  rationale: `${question} rationale`,
  source_context: "",
  directive_id: null,
  starred: false,
  dismissed: false,
  created_at: at(5),
  answered: false,
  answer_summary: "",
  needs_followup: false,
  followup_question: "",
  ...extra,
});

const briefing = (overrides = {}) => ({
  id: "syn-1",
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
  created_at: at(35),
  updated_at: null,
  clusters: [],
  ...overrides,
});

const segment = (n, start, end) => ({ id: `seg-${n}`, session_id: "session-1", segment_number: n, started_at: start, ended_at: end });

test("with a briefing, commitments are its action plan and the live count is stated", async () => {
  const { commitments } = await load();
  const questions = [
    insight("a-1", "action_item", "Send the pricing deck by Friday."),
    insight("a-2", "action_item", "Book the architecture review", { starred: true }),
    insight("a-3", "action_item", "Dismissed one", { dismissed: true }),
  ];
  const synthesis = briefing({
    action_plan: [
      { title: "Send the deck", summary: "The arbiter rephrased it", owner: "Maya" },
      { title: "Loop in procurement", summary: "Before the SOW", owner: "Drew", status: "Pending" },
      { title: "", summary: "" },
    ],
  });

  const list = commitments(questions, synthesis);

  assert.equal(list.source, "briefing");
  assert.equal(list.total, 2);
  assert.deepEqual(list.items.map((item) => item.title), ["Send the deck", "Loop in procurement"]);
  assert.equal(list.items[1].owner, "Drew");
  assert.equal(list.items[1].status, "Pending");
  // Two live action items (the dismissed one is not counted), all shown by the filter.
  assert.deepEqual(list.insights, { matching: 2, shown: 2, filter: "action_item" });
});

test("without a briefing, commitments are the live action items, starred first, capped", async () => {
  const { commitments, COMMITMENT_CAP } = await load();
  const questions = [
    ...Array.from({ length: 9 }, (_, i) => insight(`a-${i}`, "action_item", `Action ${i}`)),
    insight("a-star", "action_item", "Starred action", { starred: true }),
  ];
  const list = commitments(questions, null);
  assert.equal(list.source, "insights");
  assert.equal(list.items.length, COMMITMENT_CAP);
  assert.equal(list.total, 10);
  assert.equal(list.items[0].title, "Starred action");
  assert.equal(list.items[0].status, "Starred");
  assert.equal(list.items[0].insightId, "a-star");
  // An empty briefing section falls back the same way.
  assert.equal(commitments(questions, briefing()).source, "insights");
});

test("open loops are unanswered questions, follow-ups first, against every question the filter shows", async () => {
  const { openLoops } = await load();
  const questions = [
    insight("q-1", "question", "What is the budget?"),
    insight("q-2", "question", "Who signs?", { answered: true }),
    insight("q-3", "question", "When is go-live?", { needs_followup: true, answered: true }),
    insight("o-1", "observation", "Not a question", { starred: true }),
    insight("k-1", "asked", "My own question", { starred: true }),
    insight("x-1", "question", "Dismissed", { dismissed: true }),
  ];

  const list = openLoops(questions, null);

  assert.equal(list.source, "insights");
  assert.deepEqual(list.items.map((item) => item.title), ["When is go-live?", "What is the budget?"]);
  assert.equal(list.items[0].status, "Needs follow-up");
  assert.equal(list.items[1].status, undefined);
  // Three live questions in the filter, two of them open.
  assert.deepEqual(list.insights, { matching: 2, shown: 3, filter: "question" });
});

test("with a briefing, open loops are its unresolved questions", async () => {
  const { openLoops } = await load();
  const questions = [insight("q-1", "question", "What is the budget?")];
  const synthesis = briefing({
    unresolved_discovery_questions: [{ title: "Which region first?", summary: "Not settled" }],
  });
  const list = openLoops(questions, synthesis);
  assert.equal(list.source, "briefing");
  assert.deepEqual(list.items.map((item) => item.title), ["Which region first?"]);
  assert.equal(list.items[0].detail, "Not settled");
  assert.deepEqual(list.insights, { matching: 1, shown: 1, filter: "question" });
});

test("risks are Risk-badged current signals, stated against all current signals", async () => {
  const { risks } = await load();
  const questions = [
    insight("h-1", "signal_history", "Old risk", { lens_label: "Risk" }),
    insight("s-1", "signal", "Live risk", { lens_label: "Risk" }),
    insight("s-2", "signal", "Not a risk", { lens_label: "Action Cue" }),
    insight("s-3", "signal", "Another cue", { lens_label: "Signal" }),
    insight("s-4", "signal", "Dismissed risk", { lens_label: "Risk", dismissed: true }),
  ];

  const list = risks(questions, null);

  assert.equal(list.source, "insights");
  assert.deepEqual(list.items.map((item) => item.title), ["Live risk"]);
  assert.deepEqual(list.insights, { matching: 1, shown: 3, filter: "signal" });

  const withBriefing = risks(questions, briefing({ risks_blockers: [{ title: "Procurement freeze", summary: "Q4" }] }));
  assert.equal(withBriefing.source, "briefing");
  assert.deepEqual(withBriefing.items.map((item) => item.title), ["Procurement freeze"]);
  assert.equal(withBriefing.total, 1);
  assert.deepEqual(withBriefing.insights, { matching: 1, shown: 3, filter: "signal" });
});

test("opportunities lead with starred insights and name offering matches", async () => {
  const { opportunities } = await load();
  const questions = [
    insight("p-1", "opportunity", "Managed detection", { offering_match: "MDR" }),
    insight("p-2", "opportunity", "Network refresh", { starred: true }),
  ];
  const list = opportunities(questions, null);
  assert.deepEqual(list.items.map((item) => item.title), ["Network refresh", "Managed detection"]);
  assert.equal(list.items[0].status, "Starred");
  assert.equal(list.items[1].status, "Matched to an offering");
  assert.deepEqual(list.insights, { matching: 2, shown: 2, filter: "opportunity" });

  const withBriefing = opportunities(questions, briefing({ top_opportunities: [{ title: "Refresh the core", summary: "" }] }));
  assert.equal(withBriefing.source, "briefing");
  assert.equal(withBriefing.total, 1);
  assert.equal(withBriefing.insights.matching, 2);
});

test("participation measures word share and floor changes, folding unknown speakers together", async () => {
  const { participation, UNATTRIBUTED_COLOR } = await load();
  const speakers = [
    { id: "sp-a", name: "Auto 1", display_name: "Patrick", display_name_enabled: true, color: "#111111" },
    { id: "sp-b", name: "Auto 2", display_name: "Ignored", display_name_enabled: false, color: "#222222" },
  ];
  const transcripts = [
    { text: "one two three four", timestamp: at(1), speaker_id: "sp-a" },
    { text: "five six", timestamp: at(2), speaker_id: "sp-a" },
    { text: "seven eight nine", timestamp: at(3), speaker_id: "sp-b" },
    { text: "ten", timestamp: at(4), speaker_id: null },
    { text: "   ", timestamp: at(5), speaker_id: "sp-b" },
    { text: "eleven twelve", timestamp: at(6), speaker_id: "sp-a" },
    { text: "thirteen", timestamp: at(7), speaker_id: "missing-speaker" },
  ];

  const rows = participation(transcripts, speakers);

  assert.deepEqual(rows.map((row) => [row.name, row.words, row.turns]), [
    ["Patrick", 8, 2],
    ["Auto 2", 3, 1],
    ["Unattributed", 2, 2],
  ]);
  assert.equal(rows[0].color, "#111111");
  assert.equal(rows[2].color, UNATTRIBUTED_COLOR);
  assert.ok(Math.abs(rows.reduce((sum, row) => sum + row.share, 0) - 1) < 1e-9);
  assert.equal(participation([], speakers).length, 0);
});

test("call rhythm buckets insights into five-minute windows of call time and names the busiest", async () => {
  const { callRhythm } = await load();
  const segments = [segment(1, at(0), at(34))];
  const questions = [
    insight("q-1", "question", "a", { created_at: at(1) }),
    insight("q-2", "question", "b", { created_at: at(16) }),
    insight("q-3", "question", "c", { created_at: at(17) }),
    insight("q-4", "question", "d", { created_at: at(19) }),
    insight("q-5", "question", "e", { created_at: at(33) }),
    insight("q-7", "question", "gone", { created_at: at(18), dismissed: true }),
  ];

  const rhythm = callRhythm(questions, session, segments);

  assert.ok(rhythm);
  assert.equal(rhythm.buckets.length, 7);
  assert.deepEqual(rhythm.buckets.map((bucket) => bucket.count), [1, 0, 0, 3, 0, 0, 1]);
  assert.equal(rhythm.busiest, 3);
  assert.equal(rhythm.peak, 3);
  assert.equal(rhythm.total, 5);
  assert.deepEqual(rhythm.breaks, []);
  assert.equal(rhythm.segments, 1);
});

test("a resumed call is measured in call time: segments concatenate and the gap takes no room", async () => {
  const { callRhythm, totalCallMs } = await load();
  // Ten minutes of call, an eleven-hour break, then fifteen more minutes.
  const resumeStart = new Date(Date.UTC(2026, 8, 2, 7, 0)).toISOString();
  const resumeEnd = new Date(Date.UTC(2026, 8, 2, 7, 15)).toISOString();
  const laterMinutes = (m) => new Date(Date.UTC(2026, 8, 2, 7, m)).toISOString();
  const segments = [segment(1, at(0), at(10)), segment(2, resumeStart, resumeEnd)];
  const questions = [
    insight("q-1", "question", "first call", { created_at: at(3) }),
    insight("q-2", "question", "resume early", { created_at: laterMinutes(2) }),
    insight("q-3", "question", "resume late", { created_at: laterMinutes(14) }),
    // Written during the break: snaps to the nearest edge (end of segment one).
    insight("q-4", "question", "during the pause", { created_at: at(40) }),
    // Written by the final pass after the resume ended: snaps to the last edge.
    insight("q-5", "question", "after the call", { created_at: laterMinutes(30) }),
  ];

  const rhythm = callRhythm(questions, { ...session, ended_at: resumeEnd }, segments);

  assert.ok(rhythm);
  // 25 minutes of call time -> five buckets, not the 650 the wall clock spans.
  // The pause insight snaps to the end of segment one (10 min, the seam) and
  // the resume's early insight lands at 12 min, so both sit in bucket 10-15;
  // the late resume insight (24 min) and the post-call one (clamped to 25
  // min) share the last bucket.
  assert.equal(rhythm.buckets.length, 5);
  assert.deepEqual(rhythm.buckets.map((bucket) => bucket.count), [1, 0, 2, 0, 2]);
  assert.deepEqual(rhythm.breaks, [10 * 60 * 1000]);
  assert.equal(rhythm.segments, 2);
  assert.equal(rhythm.total, 5);
  assert.equal(totalCallMs(session, segments), 25 * 60 * 1000);
});

test("an open last segment closes at the latest insight or transcript instead of losing its insights", async () => {
  const { callRhythm, callWindows } = await load();
  const segments = [segment(1, at(0), at(10)), segment(2, at(20), null)];
  const questions = [
    insight("q-1", "question", "first", { created_at: at(3) }),
    insight("q-2", "question", "resumed", { created_at: at(27) }),
  ];
  const transcripts = [{ text: "still talking", timestamp: at(31), speaker_id: null }];
  const open = { ...session, ended_at: null };

  const windows = callWindows(open, segments, { questions, transcripts });
  assert.equal(windows.length, 2);
  assert.equal(windows[1].endMs, Date.parse(at(31)));

  const rhythm = callRhythm(questions, open, segments, transcripts);
  assert.ok(rhythm);
  // 10 + 11 minutes of call time -> five buckets; the resumed insight lands at 17 min.
  assert.equal(rhythm.buckets.length, 5);
  assert.deepEqual(rhythm.buckets.map((bucket) => bucket.count), [1, 0, 0, 1, 0]);
});

test("call rhythm is omitted without a call window or without timestamped insights", async () => {
  const { callRhythm } = await load();
  const noWindow = { ...session, started_at: null, ended_at: null };
  assert.equal(callRhythm([insight("q-1", "question", "a")], noWindow, []), null);
  assert.equal(callRhythm([], session, []), null);
  assert.equal(callRhythm([insight("q-1", "question", "a", { created_at: "not a date" })], session, []), null);
});

test("total call time sums recorded segments and falls back to the session span", async () => {
  const { totalCallMs, formatMinutes } = await load();
  const segments = [segment(1, at(0), at(10)), segment(2, at(20), at(34))];
  assert.equal(totalCallMs(session, segments), 24 * 60 * 1000);
  assert.equal(totalCallMs(session, []), 34 * 60 * 1000);
  assert.equal(formatMinutes(24 * 60 * 1000), "24 min");
  assert.equal(formatMinutes(95 * 60 * 1000), "1h 35m");
  assert.equal(formatMinutes(20 * 1000), "under a minute");
});

test("the headline is the briefing's top outcome when there is one", async () => {
  const { headline } = await load();
  const synthesis = briefing({
    top_outcomes: [{ title: "", summary: "" }, { title: "Agreed on a Q4 pilot", summary: "Two sites, 90 days", rationale: "why" }],
  });
  const lead = headline(session, synthesis, [], [], []);
  assert.equal(lead.source, "briefing");
  assert.equal(lead.text, "Agreed on a Q4 pilot");
  assert.equal(lead.detail, "Two sites, 90 days");
});

test("the headline falls back to honest counts and says so", async () => {
  const { headline } = await load();
  const speakers = [{ id: "sp-a", name: "A" }, { id: "sp-b", name: "B" }];
  const questions = [
    insight("q-1", "question", "open"),
    insight("q-2", "question", "answered", { answered: true }),
    insight("a-1", "action_item", "do"),
    insight("x-1", "question", "gone", { dismissed: true }),
  ];
  const lead = headline(session, null, questions, speakers, []);
  assert.equal(lead.source, "derived");
  assert.equal(lead.text, "34 min on the call with 2 speakers.");
  assert.equal(lead.detail, "3 insights, 1 action item, 1 open question.");

  const empty = headline({ ...session, started_at: null, ended_at: null }, null, [], [], []);
  assert.equal(empty.text, "No call audio was recorded.");
  assert.match(empty.detail, /No insights/);
});
