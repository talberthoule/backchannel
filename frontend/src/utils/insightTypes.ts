import type { Question } from "../types";

// Built-in insight types with fixed branding. Custom lens types get a stable
// palette color hashed from their slug and labels derived from the producing
// lens (lens_label) or a humanized slug.
export const BUILTIN_TYPE_META: Record<string, { label: string; plural: string; color: string }> = {
  // The operator's own questions. Deliberately a neutral rather than a sixth
  // hue: the five agent types already hold teal, amber, violet, emerald and
  // red, and an answer to your own question is not another finding category.
  asked: { label: "You asked", plural: "Asked", color: "#475569" },
  question: { label: "Question", plural: "Questions", color: "#0d9488" },
  objection: { label: "Objection", plural: "Objections", color: "#f59e0b" },
  observation: { label: "Observation", plural: "Observations", color: "#7c3aed" },
  opportunity: { label: "Opportunity", plural: "Opportunities", color: "#10b981" },
  action_item: { label: "Action Item", plural: "Action Items", color: "#e2231a" },
  // Strategic signals the live panel did not have room for, and the ones that
  // have since aged out of the current cycle (ALP-308). Each row's lens_label
  // carries the section it came from, so the card badge still reads "Risk" or
  // "Next Question" rather than a flat "Strategic".
  signal: { label: "Strategic Signal", plural: "Strategic", color: "#0284c7" },
  signal_history: { label: "Past Signal", plural: "History", color: "#64748b" },
};

// Types whose lens_label is a per-row section badge (Signal, Risk, Next
// Question, Opportunity, Action Cue - see SIGNAL_SECTIONS in
// backend/app/services/agents/signal_insights.py) rather than the heading of
// the lens that produced the whole group. Group labels for these must never
// be derived from the rows: a cycle with one row per section and a history of
// mostly action cues both used to render as a second "Action Cue" group.
// The live chips keep the short plurals above (Strategic, History; see
// docs/agents.md); the post-call group headings get these fuller names.
const SIGNAL_GROUP_LABELS: Record<string, string> = {
  signal: "Strategic Signals",
  signal_history: "Signal History",
};

// Display order for type groupings; custom types sort after built-ins.
export const BUILTIN_TYPE_ORDER = ["asked", "signal", "action_item", "objection", "opportunity", "observation", "question", "signal_history"];

const CUSTOM_TYPE_COLORS = ["#0284c7", "#c026d3", "#ea580c", "#4f46e5", "#0891b2", "#65a30d", "#be185d", "#7c2d12"];

export function humanizeTypeSlug(slug: string): string {
  return (slug || "insight")
    .split("_")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function typeColor(itemType: string): string {
  const meta = BUILTIN_TYPE_META[itemType];
  if (meta) return meta.color;
  let hash = 0;
  for (let i = 0; i < itemType.length; i++) hash = (hash * 31 + itemType.charCodeAt(i)) >>> 0;
  return CUSTOM_TYPE_COLORS[hash % CUSTOM_TYPE_COLORS.length];
}

// Singular badge label: the producing lens heading wins, then built-in label,
// then a humanized slug for custom types.
export function typeLabel(itemType: string, lensLabel?: string): string {
  if (lensLabel && lensLabel.trim()) return lensLabel.trim();
  return BUILTIN_TYPE_META[itemType]?.label ?? humanizeTypeSlug(itemType);
}

// Group/section heading for a set of same-type insights: prefer the most
// common lens heading among them so renamed lenses surface everywhere.
// Signal rows are the exception - their lens_label is the section badge of
// each individual row, so a fixed group name is the only honest one.
export function typeGroupLabel(itemType: string, questions: Question[]): string {
  const fixed = SIGNAL_GROUP_LABELS[itemType];
  if (fixed) return fixed;
  const counts = new Map<string, number>();
  for (const q of questions) {
    const label = (q.lens_label || "").trim();
    if (label) counts.set(label, (counts.get(label) || 0) + 1);
  }
  let best = "";
  let bestCount = 0;
  for (const [label, count] of counts) {
    if (count > bestCount) {
      best = label;
      bestCount = count;
    }
  }
  if (best) return best;
  return BUILTIN_TYPE_META[itemType]?.plural ?? humanizeTypeSlug(itemType);
}

// The Strategic filter carries every current signal plus this many of the most
// recently retired ones, so it reads as "the strategic picture right now"
// rather than only the current cycle's output. The full trail stays under
// History; the borrowed rows appear in both.
export const RECENT_HISTORY_IN_STRATEGIC = 3;

// The signal_history rows the Strategic filter borrows: the most recently
// retired first. Retirement stamps updated_at (see sync_signal_insights);
// created_at is the fallback for rows that predate that stamp.
export function recentSignalHistoryIds(
  questions: Question[],
  limit: number = RECENT_HISTORY_IN_STRATEGIC,
): Set<string> {
  const retiredAtMs = (q: Question) => {
    const value = Date.parse(q.updated_at || q.created_at);
    return Number.isFinite(value) ? value : 0;
  };
  return new Set(
    questions
      .filter((q) => (q.item_type || "question") === "signal_history" && !q.dismissed)
      .sort((a, b) => retiredAtMs(b) - retiredAtMs(a) || a.id.localeCompare(b.id))
      .slice(0, limit)
      .map((q) => q.id),
  );
}

// Ordered distinct item types present in a question list: built-ins in fixed
// order first, then custom types in first-seen order.
export function presentTypes(questions: Question[]): string[] {
  const present = new Set<string>();
  const customs: string[] = [];
  for (const q of questions) {
    const t = q.item_type || "question";
    if (!present.has(t)) {
      present.add(t);
      if (!BUILTIN_TYPE_META[t]) customs.push(t);
    }
  }
  return [...BUILTIN_TYPE_ORDER.filter((t) => present.has(t)), ...customs];
}

export function visibleEnrichmentNotes(notes?: string): string[] {
  return (notes || "")
    .split("\n")
    .map((note) => note.trim())
    .filter((note) => note && note !== "Merged with another insight" && note !== "Adjusted");
}
