import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { Question } from "../../types";
import QuestionCard from "./QuestionCard";
import { sortQuestionsForLiveDisplay } from "./questionOrdering";
import { BUILTIN_TYPE_META, BUILTIN_TYPE_ORDER, presentTypes, recentSignalHistoryIds, typeGroupLabel } from "../../utils/insightTypes";

// "all", an item_type slug (built-in or custom lens type), or a status key
type Filter = string;

const STATUS_KEYS = new Set(["starred", "answered", "prioritized", "enhanced"]);
export const INSIGHT_PAGE_SIZE = 40;

interface QuestionListProps {
  questions: Question[];
  showEnhanced?: boolean;
  emptyMessage?: string;
  onStar: (id: string, starred: boolean) => void;
  onDismiss: (id: string) => void;
  onVote: (id: string, vote: number) => void;
  onMakeDirective?: (question: Question) => void;
}

const InsightRow = memo(function InsightRow({ question, showEnhanced, onStar, onDismiss, onVote, onMakeDirective }: Omit<QuestionListProps, "questions"> & { question: Question }) {
  return (
    <QuestionCard
      question={question}
      showEnhanced={showEnhanced}
      onStar={(starred) => onStar(question.id, starred)}
      onDismiss={() => onDismiss(question.id)}
      onVote={(vote) => onVote(question.id, vote)}
      onMakeDirective={onMakeDirective ? () => onMakeDirective(question) : undefined}
    />
  );
});

export default memo(function QuestionList({ questions, showEnhanced = false, emptyMessage, onStar, onDismiss, onVote, onMakeDirective }: QuestionListProps) {
  const [activeFilters, setActiveFilters] = useState<Set<Filter>>(new Set(["all"]));
  const [requestedPage, setRequestedPage] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  // The Strategic chip is the whole strategic picture: every current signal -
  // the panel's top three included, so a panel card and its own insight row
  // may both be visible (ALP-308's suppression, reversed by user request) -
  // plus the most recently retired signals, which keep their place under
  // History as well.
  const strategicExtras = useMemo(() => recentSignalHistoryIds(questions), [questions]);

  const toggleFilter = (key: Filter) => {
    setRequestedPage(0);
    setActiveFilters((prev) => {
      if (key === "all") {
        return new Set(["all"]);
      }
      const next = new Set(prev);
      next.delete("all");
      if (next.has(key)) {
        next.delete(key);
        if (next.size === 0) return new Set(["all"]);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  // Type chips: the five built-ins always, plus any custom lens types present
  // in the current insight list (labeled by their producing lens's heading).
  const typeFilterDefs = useMemo(() => {
    const present = presentTypes(questions);
    const customs = present.filter((t) => !BUILTIN_TYPE_META[t]);
    return [
      ...BUILTIN_TYPE_ORDER.map((t) => ({ key: t, label: BUILTIN_TYPE_META[t].plural })),
      ...customs.map((t) => ({
        key: t,
        label: typeGroupLabel(t, questions.filter((q) => (q.item_type || "question") === t)),
      })),
    ];
  }, [questions]);

  const filtered = useMemo(() => {
    const sorted = sortQuestionsForLiveDisplay(questions);

    if (activeFilters.has("all")) {
      return sorted.filter((q) => !q.dismissed);
    }

    const typeFilters = new Set(
      [...activeFilters].filter((f) => !STATUS_KEYS.has(f) && f !== "all")
    );

    return sorted.filter((q) => {
      const hasStarred = activeFilters.has("starred");
      const hasAnswered = activeFilters.has("answered");
      const hasPrioritized = activeFilters.has("prioritized");
      const hasEnhanced = showEnhanced && activeFilters.has("enhanced");

      const hasTypeFilter = typeFilters.size > 0;
      const hasStatusFilter = hasStarred || hasAnswered || hasPrioritized || hasEnhanced;

      const itemType = q.item_type || "question";
      // A recently retired signal answers to the Strategic chip too, so that
      // filter shows the current cycle plus the freshest history.
      const matchesType =
        typeFilters.has(itemType)
        || (itemType === "signal_history" && typeFilters.has("signal") && strategicExtras.has(q.id));
      const matchesStatus =
        (hasStarred && q.starred) ||
        (hasAnswered && q.answered) ||
        (hasPrioritized && (q.vote ?? 0) > 0) ||
        (hasEnhanced && q.enhanced);

      if (hasTypeFilter && !hasStatusFilter) return !q.dismissed && matchesType;
      if (hasStatusFilter && !hasTypeFilter) return !q.dismissed && matchesStatus;
      if (hasTypeFilter && hasStatusFilter) return !q.dismissed && matchesType && matchesStatus;
      return !q.dismissed;
    });
  }, [questions, strategicExtras, activeFilters, showEnhanced]);

  // Bound mounted cards, not stored insights. Counts and filtering still use
  // the complete collection; paging never drops meeting data.
  const pageCount = Math.max(1, Math.ceil(filtered.length / INSIGHT_PAGE_SIZE));
  const page = Math.min(requestedPage, pageCount - 1);
  const pageStart = page * INSIGHT_PAGE_SIZE;
  const pageItems = filtered.slice(pageStart, pageStart + INSIGHT_PAGE_SIZE);

  useEffect(() => {
    // Dismissing the last item on the last page must not leave an empty page
    // or jump back there if new insights subsequently arrive.
    setRequestedPage(page);
  }, [page]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [page, activeFilters]);

  const filters: { key: Filter; label: string }[] = [
    { key: "all", label: "All" },
    ...typeFilterDefs,
    { key: "starred", label: "Starred" },
    { key: "answered", label: "Answered" },
    { key: "prioritized", label: "Prioritized" },
    ...(showEnhanced ? [{ key: "enhanced", label: "Enhanced" }] : []),
  ];

  // Per-chip counts over the live (non-dismissed) items, so every tab shows
  // where the insights are before the user clicks it.
  const filterCounts = useMemo(() => {
    const counts = new Map<Filter, number>();
    const live = questions.filter((q) => !q.dismissed);
    counts.set("all", live.length);
    const bump = (key: Filter) => counts.set(key, (counts.get(key) || 0) + 1);
    for (const q of live) {
      bump(q.item_type || "question");
      // A borrowed history row counts under Strategic too, matching the
      // filter predicate above; it is deliberately in both chips' counts.
      if ((q.item_type || "question") === "signal_history" && strategicExtras.has(q.id)) bump("signal");
      if (q.starred) bump("starred");
      if (q.answered) bump("answered");
      if ((q.vote ?? 0) > 0) bump("prioritized");
      if (q.enhanced) bump("enhanced");
    }
    return counts;
  }, [questions, strategicExtras]);

  // An empty chip is a promise of nothing. Only All (the reset) and whatever is
  // currently selected survive a zero count - the selected one so a filter that
  // empties out can still be switched off.
  const visibleFilters = filters.filter(
    ({ key }) => key === "all" || activeFilters.has(key) || (filterCounts.get(key) || 0) > 0,
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Filter controls: one consistent chip design for every tab; the
          selected tabs fill teal while the rest stay quiet outlines. */}
      <div className="flex shrink-0 flex-wrap items-center gap-1.5 border-b border-brand-light-gray-1 px-4 pb-3">
        {visibleFilters.map(({ key, label }) => {
          const active = activeFilters.has(key);
          const count = filterCounts.get(key) || 0;
          return (
            <button
              key={key}
              onClick={() => toggleFilter(key)}
              aria-pressed={active}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-body text-sm font-medium transition-colors ${
                active
                  ? "border-brand-teal bg-brand-teal text-white"
                  : count === 0
                    ? "border-brand-light-gray-1 bg-surface text-brand-mid-gray hover:border-brand-teal/40 hover:text-brand-gray"
                    : "border-brand-light-gray-1 bg-surface text-brand-gray hover:border-brand-teal/40 hover:text-brand-dark-gray"
              }`}
            >
              {label}
              <span
                className={`font-mono text-xs tabular-nums ${
                  active ? "text-white/80" : "text-brand-mid-gray"
                }`}
              >
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Scrollable list */}
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <p className="font-body text-sm text-brand-mid-gray">
              {activeFilters.has("all")
                ? emptyMessage || "No active items. Waiting for conversation..."
                : "No items match the selected filters."}
            </p>
          </div>
        ) : (
          pageItems.map((q) => (
            <InsightRow
              key={q.id}
              question={q}
              showEnhanced={showEnhanced}
              onStar={onStar}
              onDismiss={onDismiss}
              onVote={onVote}
              onMakeDirective={onMakeDirective}
            />
          ))
        )}
      </div>
      {pageCount > 1 && (
        <nav aria-label="Insight pages" className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-brand-light-gray-1 px-4 py-2">
          <span role="status" className="font-body text-sm tabular-nums text-brand-gray">
            {pageStart + 1}-{Math.min(pageStart + INSIGHT_PAGE_SIZE, filtered.length)} of {filtered.length} insights
          </span>
          <div className="flex items-center gap-1">
            {[
              { label: "First", target: 0, disabled: page === 0 },
              { label: "Previous", target: page - 1, disabled: page === 0 },
              { label: "Next", target: page + 1, disabled: page === pageCount - 1 },
              { label: "Last", target: pageCount - 1, disabled: page === pageCount - 1 },
            ].map(({ label, target, disabled }) => (
              <button
                key={label}
                type="button"
                aria-label={`${label} insight page`}
                disabled={disabled}
                onClick={() => setRequestedPage(target)}
                className="min-h-11 rounded-md px-2 font-body text-sm text-brand-dark-gray hover:bg-brand-light-gray-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-teal disabled:cursor-not-allowed disabled:opacity-40"
              >
                {label}
              </button>
            ))}
          </div>
        </nav>
      )}
    </div>
  );
});
