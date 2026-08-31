import { useEffect, useMemo, useState } from "react";
import type { Session, SessionSynthesis, SynthesisSectionItem } from "../../types";

interface SynthesisSignalsProps {
  session: Session;
  synthesis: SessionSynthesis | null;
}

export interface LiveSignalCard {
  key: string;
  label: string;
  item: SynthesisSectionItem;
}

// The call screen is busy enough for three panels (ALP-305). Every signal past
// the cut is filed as an ordinary insight instead, so nothing is dropped.
export const LIVE_SIGNAL_CARD_LIMIT = 3;

// Section order is the tie-break for anything the model left unranked, and the
// label each card carries. Mirrors SIGNAL_SECTIONS in
// backend/app/services/agents/signal_insights.py. Every signal - the panel's
// included - is also an ordinary insight row in the list below (ALP-308; the
// original suppression of panel rows was reversed by user request).
const SIGNAL_SECTIONS = [
  { section: "strategic_signals", key: "signal", label: "Signal" },
  { section: "risks_blockers", key: "risk", label: "Risk" },
  { section: "unresolved_discovery_questions", key: "next-question", label: "Next Question" },
  { section: "top_opportunities", key: "opportunity", label: "Opportunity" },
  { section: "action_plan", key: "action-cue", label: "Action Cue" },
] as const;

// An unranked item sorts after every ranked one rather than ahead of rank 1.
const UNRANKED = 10_000;

function itemText(item: SynthesisSectionItem): string {
  return item.title?.trim() || item.summary?.trim() || "";
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

/**
 * Every signal the current cycle produced, most important first.
 *
 * The model ranks its own output with `priority` (1 is the single thing the
 * user most needs right now, numbered across all five sections together), so
 * the panel is no longer stuck showing whichever sections happen to sort first.
 * Anything left unranked falls back to section order.
 */
export function getRankedSignalCards(
  synthesis: SessionSynthesis | null,
  session?: Pick<Session, "meeting_type">,
): LiveSignalCard[] {
  if (!synthesis || synthesis.mode !== "live") {
    return [];
  }

  const ranked: { card: LiveSignalCard; sort: [number, number, number] }[] = [];
  SIGNAL_SECTIONS.forEach(({ section, key, label }, sectionIndex) => {
    const items = (synthesis[section] as SynthesisSectionItem[] | undefined) || [];
    items.forEach((item, itemIndex) => {
      if (!itemText(item)) return;
      const priority = item.priority ?? 0;
      ranked.push({
        card: {
          key: itemIndex === 0 ? key : `${key}-${itemIndex}`,
          label: section === "top_opportunities" ? opportunityLabel(session?.meeting_type) : label,
          item,
        },
        sort: [priority > 0 ? priority : UNRANKED, sectionIndex, itemIndex],
      });
    });
  });

  ranked.sort((a, b) => a.sort[0] - b.sort[0] || a.sort[1] - b.sort[1] || a.sort[2] - b.sort[2]);

  // Two sections can return the same observation; the higher-ranked one wins
  // rather than the panel spending two of its three slots saying it twice.
  const seen = new Set<string>();
  const cards: LiveSignalCard[] = [];
  for (const { card } of ranked) {
    const identity = signalIdentity(itemText(card.item));
    if (!identity || seen.has(identity)) continue;
    seen.add(identity);
    cards.push(card);
  }
  return cards;
}

// Matches _signal_identity in backend/app/services/briefing_synthesis.py, so a
// signal merged into history and the same signal still on the current cycle
// collapse to one entry here too.
function signalIdentity(value: string | undefined): string {
  return (value || "").replace(/\s+/g, " ").toLowerCase().trim().replace(/[ .,:;!?]+$/, "");
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
    () => getRankedSignalCards(synthesis, session).slice(0, LIVE_SIGNAL_CARD_LIMIT),
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
