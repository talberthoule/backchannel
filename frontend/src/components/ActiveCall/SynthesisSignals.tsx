import { useEffect, useMemo, useState } from "react";
import type { Session, SessionSynthesis, SignalHistoryItem, SynthesisSectionItem } from "../../types";

interface SynthesisSignalsProps {
  session: Session;
  synthesis: SessionSynthesis | null;
}

export interface LiveSignalCard {
  key: string;
  label: string;
  item: SynthesisSectionItem;
}

// The call screen is busy enough for three panels (ALP-305). Every candidate
// signal is still captured and scored - the ones past the cut stay available
// under the insight list's Strategic filter and keep feeding later analysis.
export const LIVE_SIGNAL_CARD_LIMIT = 3;

function first(items: SynthesisSectionItem[] | undefined): SynthesisSectionItem | null {
  return items?.find((item) => itemText(item)) ?? null;
}

function itemText(item: SynthesisSectionItem): string {
  return item.title?.trim() || item.summary?.trim() || "";
}

function refString(ref: Record<string, unknown>, key: string): string {
  const value = ref[key];
  return typeof value === "string" ? value.trim() : "";
}

function evidenceValues(refs: Record<string, unknown>[] | undefined): Set<string> {
  const values = new Set<string>();
  for (const ref of refs || []) {
    for (const key of ["id", "insight_id", "transcript_id", "source_id"]) {
      const value = refString(ref, key);
      if (value) values.add(value);
    }
  }
  return values;
}

function addInsightIds(ids: Set<string>, refs: Record<string, unknown>[] | undefined) {
  for (const ref of refs || []) {
    const type = refString(ref, "type").toLowerCase();
    const insightId = refString(ref, "insight_id");
    const id = refString(ref, "id");
    const sourceId = refString(ref, "source_id");

    if (insightId) ids.add(insightId);
    if (!type || type === "insight") {
      if (id) ids.add(id);
      if (sourceId) ids.add(sourceId);
    }
  }
}

function intersects(a: Set<string>, b: Set<string>): boolean {
  for (const value of a) {
    if (b.has(value)) return true;
  }
  return false;
}

function opportunityLabel(meetingType?: Session["meeting_type"]): string {
  switch (meetingType) {
    case "internal_enablement":
      return "Enablement";
    case "vendor_partner":
      return "Partner";
    case "customer_delivery":
      return "Delivery";
    case "internal_checkin":
      return "Support";
    default:
      return "Opportunity";
  }
}

export function getLiveSignalCards(synthesis: SessionSynthesis | null, session?: Pick<Session, "meeting_type">): LiveSignalCard[] {
  if (!synthesis || synthesis.mode !== "live") {
    return [];
  }

  const signals = synthesis.strategic_signals || [];
  return [
    { key: "signal", label: "Signal", item: first(signals) || first(synthesis.top_outcomes) },
    { key: "risk", label: "Risk", item: first(synthesis.risks_blockers) },
    { key: "next-question", label: "Next Question", item: first(synthesis.unresolved_discovery_questions) },
    { key: "opportunity", label: opportunityLabel(session?.meeting_type), item: first(synthesis.top_opportunities) },
    { key: "action-cue", label: "Action Cue", item: first(synthesis.action_plan) },
  ].filter((card): card is LiveSignalCard => card.item !== null);
}

// Matches _signal_identity in backend/app/services/briefing_synthesis.py, so a
// signal merged into history and the same signal still on the current cycle
// collapse to one entry here too.
function signalIdentity(value: string | undefined): string {
  return (value || "").replace(/\s+/g, " ").toLowerCase().trim().replace(/[ .,:;!?]+$/, "");
}

/**
 * Every strategic signal this call has captured, newest first: the merged
 * history plus any current-cycle signal not yet in it. This is the full record
 * the panel's top three are drawn from, and what the Strategic insight filter
 * lists.
 */
export function getStrategicSignalItems(synthesis: SessionSynthesis | null): SignalHistoryItem[] {
  if (!synthesis || synthesis.mode !== "live") {
    return [];
  }

  const byKey = new Map<string, SignalHistoryItem>();
  for (const item of synthesis.signal_history || []) {
    const identity = signalIdentity(item.title || item.summary);
    if (identity) byKey.set(`${item.section}:${identity}`, item);
  }

  // A cycle's signals reach the client before the next history read does, so
  // fill any gap from the current cycle. History wins where both have it: it
  // carries first_seen and the seen count.
  const stamp = synthesis.updated_at || synthesis.created_at;
  for (const item of synthesis.strategic_signals || []) {
    const identity = signalIdentity(item.title || item.summary);
    if (!identity || byKey.has(`strategic_signals:${identity}`)) continue;
    byKey.set(`strategic_signals:${identity}`, {
      ...item,
      section: "strategic_signals",
      first_seen: stamp,
      last_seen: stamp,
      count: 1,
    });
  }

  return [...byKey.values()].sort(
    (a, b) => new Date(b.last_seen).getTime() - new Date(a.last_seen).getTime(),
  );
}

export function getLiveSignalInsightIds(synthesis: SessionSynthesis | null): Set<string> {
  const ids = new Set<string>();
  const cards = getLiveSignalCards(synthesis);

  for (const card of cards) {
    const cardEvidence = evidenceValues(card.item.evidence_refs);
    addInsightIds(ids, card.item.evidence_refs);

    for (const cluster of synthesis?.clusters || []) {
      const clusterEvidence = evidenceValues(cluster.evidence_refs);
      const sameTitle = itemText(card.item) && itemText(card.item) === cluster.title?.trim();
      const sameSummary = card.item.summary?.trim() && card.item.summary.trim() === cluster.summary?.trim();
      if (sameTitle || sameSummary || intersects(cardEvidence, clusterEvidence)) {
        for (const id of cluster.related_question_ids || []) {
          if (id) ids.add(id);
        }
      }
    }
  }

  return ids;
}

function SignalItem({
  card,
  isSelected,
  onSelect,
}: {
  card: LiveSignalCard;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const { label, item } = card;
  const title = itemText(item);
  const summary = item.summary?.trim() || "";
  const hasDistinctSummary = summary && item.title?.trim();
  const rationale = item.rationale?.trim() || "";
  const owner = item.owner?.trim() || "";
  const status = item.status?.trim() || "";

  if (!title) return null;

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-expanded={isSelected}
      className={`min-w-0 rounded-md border bg-surface px-3 py-2 text-left shadow-sm transition-all duration-200 focus:ring-2 focus:ring-brand-teal-light ${
        isSelected
          ? "border-brand-teal ring-1 ring-brand-teal/20 sm:col-span-2 lg:col-span-3"
          : "border-brand-light-gray-1 hover:border-brand-teal-light/60 hover:shadow"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="font-body text-[10px] font-semibold uppercase tracking-wide text-brand-mid-gray">{label}</p>
        <svg
          className={`mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-brand-mid-gray transition-transform ${isSelected ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          strokeWidth={2}
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="m6 9 6 6 6-6" />
        </svg>
      </div>
      <p className={`mt-0.5 font-body text-sm font-semibold text-brand-dark-gray ${isSelected ? "whitespace-normal" : "truncate"}`} title={title}>
        {title}
      </p>
      {hasDistinctSummary && (
        <p className={`mt-0.5 font-body text-xs leading-relaxed text-brand-gray ${isSelected ? "whitespace-normal" : "line-clamp-2"}`}>
          {summary}
        </p>
      )}
      {isSelected && (
        <div className="mt-2 space-y-1 border-t border-brand-light-gray-1 pt-2">
          {rationale && (
            <p className="font-body text-xs leading-relaxed text-brand-gray">{rationale}</p>
          )}
          {(owner || status) && (
            <p className="font-body text-[11px] text-brand-mid-gray">
              {[owner ? `Owner: ${owner}` : "", status ? `Status: ${status}` : ""].filter(Boolean).join(" | ")}
            </p>
          )}
        </div>
      )}
    </button>
  );
}

export default function SynthesisSignals({ session, synthesis }: SynthesisSignalsProps) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const cards = useMemo(
    () => getLiveSignalCards(synthesis, session).slice(0, LIVE_SIGNAL_CARD_LIMIT),
    [synthesis, session],
  );

  useEffect(() => {
    if (selectedKey && !cards.some((card) => card.key === selectedKey)) {
      setSelectedKey(null);
    }
  }, [cards, selectedKey]);

  if (cards.length === 0) {
    return null;
  }

  const updated = synthesis?.updated_at || synthesis?.created_at;

  return (
    <div className="border-b border-brand-light-gray-1 bg-brand-light-gray-2 px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-display text-xs font-semibold uppercase tracking-wide text-brand-teal">
          Live Strategic Signals
        </h2>
        {updated && (
          <span className="font-body text-[10px] text-brand-mid-gray">
            Updated {new Date(updated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((card) => (
          <SignalItem
            key={card.key}
            card={card}
            isSelected={selectedKey === card.key}
            onSelect={() => setSelectedKey((current) => (current === card.key ? null : card.key))}
          />
        ))}
      </div>
      {synthesis?.status === "partial" && (
        <p className="mt-2 font-body text-xs text-brand-amber">Briefing is based on partial model output.</p>
      )}
    </div>
  );
}
