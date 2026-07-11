import { useMemo, useState } from "react";
import type { Question, Speaker } from "../../types";
import QuestionCard from "./QuestionCard";
import { sortQuestionsForLiveDisplay } from "./questionOrdering";
import { BUILTIN_TYPE_META, BUILTIN_TYPE_ORDER, presentTypes, typeGroupLabel } from "../../utils/insightTypes";

// "all", an item_type slug (built-in or custom lens type), or a status key
type Filter = string;

const STATUS_KEYS = new Set(["starred", "answered", "prioritized", "enhanced"]);

interface QuestionListProps {
  questions: Question[];
  speakers: Speaker[];
  strategicSignalQuestionIds?: string[];
  showEnhanced?: boolean;
  onStar: (id: string, starred: boolean) => void;
  onDismiss: (id: string) => void;
  onVote: (id: string, vote: number) => void;
}

export default function QuestionList({ questions, speakers, strategicSignalQuestionIds = [], showEnhanced = false, onStar, onDismiss, onVote }: QuestionListProps) {
  const [activeFilters, setActiveFilters] = useState<Set<Filter>>(new Set(["all"]));
  const strategicSignalIdSet = useMemo(
    () => new Set(strategicSignalQuestionIds),
    [strategicSignalQuestionIds]
  );

  const toggleFilter = (key: Filter) => {
    setActiveFilters((prev) => {
      const next = new Set(prev);
      if (key === "all") {
        return new Set(["all"]);
      }
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
    const sorted = sortQuestionsForLiveDisplay(questions, strategicSignalIdSet);

    if (activeFilters.has("all")) {
      return sorted.filter((q) => !q.dismissed);
    }

    const typeFilters = new Set([...activeFilters].filter((f) => !STATUS_KEYS.has(f)));

    return sorted.filter((q) => {
      const hasStarred = activeFilters.has("starred");
      const hasAnswered = activeFilters.has("answered");
      const hasPrioritized = activeFilters.has("prioritized");
      const hasEnhanced = showEnhanced && activeFilters.has("enhanced");

      const hasTypeFilter = typeFilters.size > 0;
      const hasStatusFilter = hasStarred || hasAnswered || hasPrioritized || hasEnhanced;

      const itemType = q.item_type || "question";
      const matchesType = typeFilters.has(itemType);
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
  }, [questions, activeFilters, strategicSignalIdSet, showEnhanced]);

  const filters: { key: Filter; label: string }[] = [
    { key: "all", label: "All" },
    ...typeFilterDefs,
    { key: "starred", label: "Starred" },
    { key: "answered", label: "Answered" },
    { key: "prioritized", label: "Prioritized" },
    ...(showEnhanced ? [{ key: "enhanced", label: "Enhanced" }] : []),
  ];

  return (
    <div className="flex h-full flex-col">
      {/* Filter controls */}
      <div className="flex flex-wrap items-center gap-1 border-b border-brand-light-gray-1 px-4 pb-3">
        {filters.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => toggleFilter(key)}
            className={`rounded-full px-3 py-1 font-body text-sm font-medium transition-colors ${
              activeFilters.has(key)
                ? "bg-brand-teal text-white"
                : "text-brand-gray hover:bg-brand-light-gray-2"
            }`}
          >
            {label}
          </button>
        ))}

        <span className="ml-auto font-body text-xs text-brand-mid-gray">
          {filtered.length} item{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Scrollable list */}
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <p className="font-body text-sm text-brand-mid-gray">
              {activeFilters.has("all")
                ? "No active items. Waiting for conversation..."
                : "No items match the selected filters."}
            </p>
          </div>
        ) : (
          filtered.map((q) => (
            <QuestionCard
              key={q.id}
              question={q}
              speakers={speakers}
              isStrategicSignal={strategicSignalIdSet.has(q.id)}
              showEnhanced={showEnhanced}
              onStar={(starred) => onStar(q.id, starred)}
              onDismiss={() => onDismiss(q.id)}
              onVote={(vote) => onVote(q.id, vote)}
            />
          ))
        )}
      </div>
    </div>
  );
}
