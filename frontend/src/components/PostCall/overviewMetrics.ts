// Pure data shaping for the post-call Overview worksheet. Everything here is
// derived from records the session already holds (insights, the briefing
// synthesis, transcript entries, speakers, call segments); nothing is fetched
// and nothing is summarized by a model. Kept free of runtime imports so the
// node test runner can load it directly.
//
// Honesty rule for every section: the number on a tile is the number of rows
// the tile's link lands on, and the section footer says where the rest lives.
// When a briefing exists its arbiter has already deduplicated the action plan,
// risks, opportunities and open questions against each other, so the briefing
// section is the source and the live insight count is stated alongside it.
// Without a briefing the live insight rows are the source.

import type {
  CallSegment,
  Question,
  Session,
  SessionSynthesis,
  Speaker,
  SynthesisSectionItem,
  TranscriptEntry,
} from "../../types";

export interface OverviewItem {
  key: string;
  title: string;
  detail: string;
  owner?: string;
  // Rendered through the Briefing's StatusText so tone matches across tabs.
  status?: string;
  insightId?: string;
}

export type SectionSource = "briefing" | "insights";

export interface OverviewSection {
  source: SectionSource;
  // Capped for display; `total` is every row at the section's source.
  items: OverviewItem[];
  total: number;
  // The live-insight counterpart: how many insight rows match this section,
  // how many rows the named Insights filter shows in all, and that filter.
  insights: { matching: number; shown: number; filter: string };
}

export function normalizeText(value: string | null | undefined): string {
  return String(value || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[\s.,:;!?]+$/, "");
}

function itemType(question: Question): string {
  return question.item_type || "question";
}

function liveRows(questions: Question[]): Question[] {
  return questions.filter((q) => !q.dismissed);
}

function starredFirst(a: Question, b: Question): number {
  return Number(Boolean(b.starred)) - Number(Boolean(a.starred));
}

function fromInsight(question: Question, status?: string): OverviewItem {
  return {
    key: `insight:${question.id}`,
    title: question.question,
    detail: question.rationale || "",
    status,
    insightId: question.id,
  };
}

function briefingRows(section: string, items: SynthesisSectionItem[] | null | undefined): OverviewItem[] {
  const rows: OverviewItem[] = [];
  (items || []).forEach((item, index) => {
    const title = (item.title || "").trim() || (item.summary || "").trim();
    if (!title) return;
    const summary = (item.summary || "").trim();
    rows.push({
      key: `briefing:${section}:${index}`,
      title,
      detail: summary && summary !== title ? summary : (item.rationale || "").trim(),
      owner: (item.owner || "").trim() || undefined,
      status: (item.status || "").trim() || undefined,
    });
  });
  return rows;
}

function section(
  source: SectionSource,
  rows: OverviewItem[],
  cap: number,
  insights: OverviewSection["insights"],
): OverviewSection {
  return { source, items: rows.slice(0, cap), total: rows.length, insights };
}

export const COMMITMENT_CAP = 6;
export const OPEN_LOOP_CAP = 5;
export const OPPORTUNITY_CAP = 4;
export const RISK_CAP = 4;

export function commitments(questions: Question[], synthesis: SessionSynthesis | null, cap = COMMITMENT_CAP): OverviewSection {
  const live = liveRows(questions).filter((q) => itemType(q) === "action_item").sort(starredFirst);
  const insights = { matching: live.length, shown: live.length, filter: "action_item" };
  const plan = briefingRows("action_plan", synthesis?.action_plan);
  if (plan.length > 0) return section("briefing", plan, cap, insights);
  return section("insights", live.map((q) => fromInsight(q, q.starred ? "Starred" : undefined)), cap, insights);
}

// Questions still waiting on an answer. The Insights "question" filter shows
// every question, answered or not, so the footer states the open share.
export function openLoops(questions: Question[], synthesis: SessionSynthesis | null, cap = OPEN_LOOP_CAP): OverviewSection {
  const allQuestions = liveRows(questions).filter((q) => itemType(q) === "question");
  const open = [
    ...allQuestions.filter((q) => q.needs_followup),
    ...allQuestions.filter((q) => !q.needs_followup && !q.answered),
  ];
  const insights = { matching: open.length, shown: allQuestions.length, filter: "question" };
  const unresolved = briefingRows("unresolved_discovery_questions", synthesis?.unresolved_discovery_questions);
  if (unresolved.length > 0) return section("briefing", unresolved, cap, insights);
  return section(
    "insights",
    open.map((q) => fromInsight(q, q.needs_followup ? "Needs follow-up" : undefined)),
    cap,
    insights,
  );
}

export function opportunities(questions: Question[], synthesis: SessionSynthesis | null, cap = OPPORTUNITY_CAP): OverviewSection {
  const live = liveRows(questions).filter((q) => itemType(q) === "opportunity").sort(starredFirst);
  const insights = { matching: live.length, shown: live.length, filter: "opportunity" };
  const top = briefingRows("top_opportunities", synthesis?.top_opportunities);
  if (top.length > 0) return section("briefing", top, cap, insights);
  return section(
    "insights",
    live.map((q) => fromInsight(q, q.offering_match ? "Matched to an offering" : q.starred ? "Starred" : undefined)),
    cap,
    insights,
  );
}

// Live risks are the current-cycle strategic signals badged "Risk" (the
// strategic-signals agent writes the section name into lens_label). The
// Insights "signal" filter shows every current signal, so the footer states
// how many of those are risks; retired risks live under Signal History.
export function risks(questions: Question[], synthesis: SessionSynthesis | null, cap = RISK_CAP): OverviewSection {
  const current = liveRows(questions).filter((q) => itemType(q) === "signal");
  const riskRows = current.filter((q) => normalizeText(q.lens_label) === "risk");
  const insights = { matching: riskRows.length, shown: current.length, filter: "signal" };
  const blockers = briefingRows("risks_blockers", synthesis?.risks_blockers);
  if (blockers.length > 0) return section("briefing", blockers, cap, insights);
  return section("insights", riskRows.map((q) => fromInsight(q)), cap, insights);
}

// --- Participation -----------------------------------------------------

export interface ParticipationRow {
  speakerId: string | null;
  name: string;
  color: string;
  words: number;
  turns: number;
  share: number; // 0..1 of all counted words
}

export const UNATTRIBUTED_COLOR = "#94a3b8";

function wordCount(text: string): number {
  const trimmed = (text || "").trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

export function speakerDisplayName(speaker: Speaker): string {
  return speaker.display_name && speaker.display_name_enabled ? speaker.display_name : speaker.name;
}

// Talk share by words spoken, with a turn counted each time the floor changes
// hands. Entries with no speaker fold into one "Unattributed" row so the bar
// still sums to the whole transcript rather than silently dropping speech.
interface Tally {
  words: number;
  turns: number;
}

// Words and floor changes per speaker id (null for unknown speakers), plus
// the grand total so shares can be taken.
function tallyWords(transcripts: TranscriptEntry[], known: Set<string>): { totals: Map<string | null, Tally>; totalWords: number } {
  const totals = new Map<string | null, Tally>();
  let previous: string | null | undefined;
  let totalWords = 0;
  for (const entry of transcripts) {
    const words = wordCount(entry.text);
    if (words === 0) continue;
    const id = entry.speaker_id && known.has(entry.speaker_id) ? entry.speaker_id : null;
    const row = totals.get(id) || { words: 0, turns: 0 };
    row.words += words;
    if (id !== previous) row.turns += 1;
    totals.set(id, row);
    previous = id;
    totalWords += words;
  }
  return { totals, totalWords };
}

// Named speakers by share, the unattributed remainder last.
function compareParticipation(a: ParticipationRow, b: ParticipationRow): number {
  if ((a.speakerId === null) !== (b.speakerId === null)) return a.speakerId === null ? 1 : -1;
  return b.words - a.words || a.name.localeCompare(b.name);
}

export function participation(transcripts: TranscriptEntry[], speakers: Speaker[]): ParticipationRow[] {
  const byId = new Map<string, Speaker>(speakers.map((s) => [s.id, s]));
  const { totals, totalWords } = tallyWords(transcripts, new Set(byId.keys()));
  if (totalWords === 0) return [];
  const rows: ParticipationRow[] = [];
  for (const [id, row] of totals) {
    const speaker = id === null ? undefined : byId.get(id);
    rows.push({
      speakerId: id,
      name: speaker ? speakerDisplayName(speaker) : "Unattributed",
      color: speaker ? speaker.color : UNATTRIBUTED_COLOR,
      words: row.words,
      turns: row.turns,
      share: row.words / totalWords,
    });
  }
  return rows.sort(compareParticipation);
}

// --- Call time and rhythm ----------------------------------------------

function parseMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

export interface CallWindow {
  startMs: number;
  endMs: number;
  // Where this window begins on the call-time axis (previous durations summed).
  offsetMs: number;
}

interface Activity {
  questions?: Question[];
  transcripts?: TranscriptEntry[];
}

// The last thing that happened, for closing a segment the backend never
// stamped an end on (a resumed call still open, or a crash mid-drain).
function latestActivityMs(session: Session, activity: Activity): number | null {
  let latest = parseMs(session.ended_at);
  for (const q of liveRows(activity.questions || [])) {
    const at = parseMs(q.created_at);
    if (at !== null && (latest === null || at > latest)) latest = at;
  }
  for (const entry of activity.transcripts || []) {
    const at = parseMs(entry.timestamp);
    if (at !== null && (latest === null || at > latest)) latest = at;
  }
  return latest;
}

// Recorded call windows in call time: each segment's wall-clock span, laid
// end to end so an eleven-hour gap before a resume takes no room. A segment
// with no end (or an end before its start) closes at the latest activity.
export function callWindows(session: Session, segments: CallSegment[], activity: Activity = {}): CallWindow[] {
  const fallbackEnd = latestActivityMs(session, activity);
  const spans = segments.length
    ? segments.map((s) => ({ start: parseMs(s.started_at), end: parseMs(s.ended_at) }))
    : [{ start: parseMs(session.started_at), end: parseMs(session.ended_at) }];
  const windows: CallWindow[] = [];
  for (const span of spans) {
    if (span.start === null) continue;
    let end = span.end;
    if (end === null || end <= span.start) end = fallbackEnd;
    if (end === null || end <= span.start) continue;
    windows.push({ startMs: span.start, endMs: end, offsetMs: 0 });
  }
  windows.sort((a, b) => a.startMs - b.startMs);
  let offset = 0;
  for (const window of windows) {
    window.offsetMs = offset;
    offset += window.endMs - window.startMs;
  }
  return windows;
}

// Time actually on the call: the sum of the windows above.
export function totalCallMs(session: Session, segments: CallSegment[], activity: Activity = {}): number {
  return callWindows(session, segments, activity).reduce((sum, w) => sum + (w.endMs - w.startMs), 0);
}

export interface RhythmBucket {
  startMs: number; // call-time offset
  count: number;
}

export interface CallRhythm {
  bucketMs: number;
  buckets: RhythmBucket[];
  // Call-time offsets where a later segment begins; drawn as thin breaks.
  breaks: number[];
  busiest: number; // index into buckets
  peak: number;
  total: number;
  segments: number;
}

export const RHYTHM_BUCKET_MS = 5 * 60 * 1000;

// Map a wall-clock instant onto the call-time axis. An instant outside every
// window (an insight written during a pause, or by the final pass after the
// call) snaps to the nearest window edge rather than being dropped.
export function toCallTime(ms: number, windows: CallWindow[]): number | null {
  if (windows.length === 0) return null;
  let best: CallWindow | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const window of windows) {
    if (ms >= window.startMs && ms <= window.endMs) return window.offsetMs + (ms - window.startMs);
    const distance = ms < window.startMs ? window.startMs - ms : ms - window.endMs;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = window;
    }
  }
  if (!best) return null;
  const clamped = Math.min(best.endMs, Math.max(best.startMs, ms));
  return best.offsetMs + (clamped - best.startMs);
}

export function callRhythm(
  questions: Question[],
  session: Session,
  segments: CallSegment[],
  transcripts: TranscriptEntry[] = [],
  bucketMs = RHYTHM_BUCKET_MS,
): CallRhythm | null {
  const windows = callWindows(session, segments, { questions, transcripts });
  if (windows.length === 0) return null;
  const span = windows.reduce((sum, w) => sum + (w.endMs - w.startMs), 0);
  const bucketCount = Math.max(1, Math.ceil(span / bucketMs));
  // Guard against a pathological window producing thousands of empty bars.
  if (bucketCount > 400) return null;
  const buckets: RhythmBucket[] = Array.from({ length: bucketCount }, (_, i) => ({ startMs: i * bucketMs, count: 0 }));
  let total = 0;
  for (const q of liveRows(questions)) {
    const at = parseMs(q.created_at);
    if (at === null) continue;
    const callTime = toCallTime(at, windows);
    if (callTime === null) continue;
    const index = Math.min(bucketCount - 1, Math.max(0, Math.floor(callTime / bucketMs)));
    buckets[index].count += 1;
    total += 1;
  }
  if (total === 0) return null;
  let busiest = 0;
  for (let i = 1; i < buckets.length; i += 1) {
    if (buckets[i].count > buckets[busiest].count) busiest = i;
  }
  return {
    bucketMs,
    buckets,
    breaks: windows.slice(1).map((w) => w.offsetMs),
    busiest,
    peak: buckets[busiest].count,
    total,
    segments: windows.length,
  };
}

// --- Headline ----------------------------------------------------------

export interface Headline {
  text: string;
  detail: string;
  // "briefing" when the sentence is the briefing's top outcome; "derived"
  // when it is only counts, which reads as a fallback and is labeled so.
  source: "briefing" | "derived";
}

export function formatMinutes(ms: number): string {
  const minutes = Math.round(ms / 60000);
  if (minutes < 1) return "under a minute";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function trimmed(value: string | null | undefined): string {
  return (value || "").trim();
}

// The briefing's first outcome that has any text: its title (or summary when
// untitled) as the sentence, and whichever of summary or rationale adds to it.
function briefingHeadline(synthesis: SessionSynthesis | null): Headline | null {
  const top = synthesis?.top_outcomes?.find((item) => trimmed(item.title) || trimmed(item.summary));
  if (!top) return null;
  const text = trimmed(top.title) || trimmed(top.summary);
  const summary = trimmed(top.summary);
  const detail = summary && summary !== text ? summary : trimmed(top.rationale);
  return { text, detail, source: "briefing" };
}

// "34 min on the call with 5 speakers." plus the insight counts.
function derivedLead(ms: number, speakerCount: number): string {
  const parts: string[] = [];
  if (ms > 0) parts.push(`${formatMinutes(ms)} on the call`);
  if (speakerCount) parts.push(plural(speakerCount, "speaker"));
  return `${parts.length ? parts.join(" with ") : "No call audio was recorded"}.`;
}

function derivedCounts(live: Question[]): string {
  if (live.length === 0) return "No insights have been captured for this session yet.";
  const actions = live.filter((q) => itemType(q) === "action_item").length;
  const open = live.filter((q) => itemType(q) === "question" && !q.answered).length;
  const counts = [plural(live.length, "insight")];
  if (actions) counts.push(plural(actions, "action item"));
  if (open) counts.push(`${open} open ${open === 1 ? "question" : "questions"}`);
  return `${counts.join(", ")}.`;
}

export function headline(
  session: Session,
  synthesis: SessionSynthesis | null,
  questions: Question[],
  speakers: Speaker[],
  segments: CallSegment[],
  transcripts: TranscriptEntry[] = [],
): Headline {
  const fromBriefing = briefingHeadline(synthesis);
  if (fromBriefing) return fromBriefing;
  const ms = totalCallMs(session, segments, { questions, transcripts });
  return { text: derivedLead(ms, speakers.length), detail: derivedCounts(liveRows(questions)), source: "derived" };
}
