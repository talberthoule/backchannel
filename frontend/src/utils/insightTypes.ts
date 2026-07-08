import type { Question } from "../types";

// Built-in insight types with fixed branding. Custom lens types get a stable
// palette color hashed from their slug and labels derived from the producing
// lens (lens_label) or a humanized slug.
export const BUILTIN_TYPE_META: Record<string, { label: string; plural: string; color: string }> = {
  question: { label: "Question", plural: "Questions", color: "#0d9488" },
  objection: { label: "Objection", plural: "Objections", color: "#f59e0b" },
  observation: { label: "Observation", plural: "Observations", color: "#7c3aed" },
  opportunity: { label: "Opportunity", plural: "Opportunities", color: "#10b981" },
  action_item: { label: "Action Item", plural: "Action Items", color: "#e2231a" },
};

// Display order for type groupings; custom types sort after built-ins.
export const BUILTIN_TYPE_ORDER = ["action_item", "objection", "opportunity", "observation", "question"];

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
export function typeGroupLabel(itemType: string, questions: Question[]): string {
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
