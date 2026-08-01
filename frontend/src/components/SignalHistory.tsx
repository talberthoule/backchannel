import { useState } from "react";
import type { SignalHistoryItem } from "../types";
import * as api from "../services/api";

const SECTION_LABELS: Record<string, string> = {
  strategic_signals: "Signal",
  risks_blockers: "Risk / Blocker",
  unresolved_discovery_questions: "Discovery Question",
  top_opportunities: "Opportunity",
  action_plan: "Action",
};

interface SignalHistoryProps {
  sessionId: string;
  count: number;
  heading?: string;
}

function historyTime(value: string): string {
  const time = new Date(value);
  return Number.isFinite(time.getTime())
    ? time.toLocaleString([], { dateStyle: "short", timeStyle: "short" })
    : "Unknown";
}

function SignalHistoryList({ items }: { items: SignalHistoryItem[] }) {
  const ordered = [...items].sort(
    (a, b) => new Date(b.last_seen).getTime() - new Date(a.last_seen).getTime(),
  );

  return (
    <div className="mt-3 grid gap-2 lg:grid-cols-2">
      {ordered.map((item, index) => {
        const title = item.title?.trim() || item.summary?.trim() || "Untitled signal";
        const summary = item.summary?.trim() || "";
        const distinctSummary = Boolean(item.title?.trim() && summary);
        return (
          <article
            key={`${item.section}:${item.title}:${item.first_seen}:${index}`}
            className="rounded-lg border border-brand-light-gray-1 bg-surface px-3 py-3"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="rounded-full bg-brand-teal/10 px-2 py-0.5 font-body text-[10px] font-semibold uppercase tracking-wide text-brand-teal">
                {SECTION_LABELS[item.section] || item.section.replace(/_/g, " ")}
              </span>
              <span className="font-body text-[11px] font-medium text-brand-mid-gray">
                {item.count === 1 ? "Seen once" : `Seen ${item.count} times`}
              </span>
            </div>
            <h4 className="mt-2 font-body text-sm font-semibold text-brand-dark-gray">{title}</h4>
            {distinctSummary && (
              <p className="mt-1 font-body text-xs leading-relaxed text-brand-gray">{summary}</p>
            )}
            {item.rationale?.trim() && (
              <p className="mt-2 font-body text-xs leading-relaxed text-brand-mid-gray">{item.rationale}</p>
            )}
            <p className="mt-2 font-body text-[11px] text-brand-mid-gray">
              First {historyTime(item.first_seen)} · Last {historyTime(item.last_seen)}
            </p>
          </article>
        );
      })}
    </div>
  );
}

export default function SignalHistory({ sessionId, count, heading }: SignalHistoryProps) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<SignalHistoryItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const panelId = `signal-history-${sessionId}`;
  const visibleCount = Math.max(count, items?.length || 0);

  if (visibleCount === 0) return null;

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const synthesis = await api.getSynthesis(sessionId, "live", true);
      setItems(synthesis?.signal_history || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signal history could not be loaded.");
    } finally {
      setLoading(false);
    }
  };

  const toggle = () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (items === null && !loading) void load();
  };

  return (
    <section className={heading ? "rounded-xl bg-surface p-5 shadow-sm" : "mt-3"}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        {heading && (
          <div>
            <h3 className="font-display text-sm font-semibold text-brand-dark-gray">{heading}</h3>
            <p className="mt-0.5 font-body text-xs text-brand-mid-gray">
              Durable signals observed across the conversation.
            </p>
          </div>
        )}
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          aria-controls={panelId}
          className="rounded-md border border-brand-teal/30 bg-surface px-3 py-1.5 font-body text-xs font-semibold text-brand-teal hover:bg-brand-teal/5"
        >
          {open ? "Hide history" : `History (${visibleCount})`}
        </button>
      </div>
      {open && (
        <div id={panelId}>
          {loading && <p className="mt-3 font-body text-xs text-brand-mid-gray">Loading signal history...</p>}
          {error && (
            <div className="mt-3 flex items-center gap-3 rounded-md border border-red-200 bg-red-50 px-3 py-2">
              <p className="font-body text-xs text-red-700">{error}</p>
              <button type="button" onClick={() => void load()} className="font-body text-xs font-semibold text-red-700 underline">
                Retry
              </button>
            </div>
          )}
          {!loading && !error && items?.length === 0 && (
            <p className="mt-3 font-body text-xs text-brand-mid-gray">No saved signal history yet.</p>
          )}
          {!loading && !error && items && items.length > 0 && <SignalHistoryList items={items} />}
        </div>
      )}
    </section>
  );
}
