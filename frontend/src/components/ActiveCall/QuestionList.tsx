import { useMemo, useState } from "react";
import type { Question, Speaker } from "../../types";
import QuestionCard from "./QuestionCard";
import { sortQuestionsForLiveDisplay } from "./questionOrdering";

type Filter = "all" | "question" | "objection" | "observation" | "opportunity" | "action_item" | "starred" | "answered" | "prioritized" | "enhanced";

interface QuestionListProps {
  questions: Question[];
  speakers: Speaker[];
  strategicSignalQuestionIds?: string[];
  onStar: (id: string, starred: boolean) => void;
  onDismiss: (id: string) => void;
  onVote: (id: string, vote: number) => void;
}

export default function QuestionList({ questions, speakers, strategicSignalQuestionIds = [], onStar, onDismiss, onVote }: QuestionListProps) {
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

  const filtered = useMemo(() => {
    const sorted = sortQuestionsForLiveDisplay(questions, strategicSignalIdSet);

    if (activeFilters.has("all")) {
      return sorted.filter((q) => !q.dismissed);
    }

    return sorted.filter((q) => {
      const typeFilters = new Set<string>();
      if (activeFilters.has("question")) typeFilters.add("question");
      if (activeFilters.has("objection")) typeFilters.add("objection");
      if (activeFilters.has("observation")) typeFilters.add("observation");
      if (activeFilters.has("opportunity")) typeFilters.add("opportunity");
      if (activeFilters.has("action_item")) typeFilters.add("action_item");

      const hasStarred = activeFilters.has("starred");
      const hasAnswered = activeFilters.has("answered");
      const hasPrioritized = activeFilters.has("prioritized");
      const hasEnhanced = activeFilters.has("enhanced");

      const hasTypeFilter = typeFilters.size > 0;
      const hasStatusFilter = hasStarred || hasAnswered || hasPrioritized || hasEnhanced;

      if (hasTypeFilter && !hasStatusFilter) {
        const itemType = q.item_type || "question";
        return !q.dismissed && typeFilters.has(itemType);
      }

      if (hasStatusFilter && !hasTypeFilter) {
        const matchesStatus =
          (hasStarred && q.starred) ||
          (hasAnswered && q.answered) ||
          (hasPrioritized && (q.vote ?? 0) > 0) ||
          (hasEnhanced && q.enhanced);
        return !q.dismissed && matchesStatus;
      }

      if (hasTypeFilter && hasStatusFilter) {
        const itemType = q.item_type || "question";
        const matchesType = typeFilters.has(itemType);
        const matchesStatus =
          (hasStarred && q.starred) ||
          (hasAnswered && q.answered) ||
          (hasPrioritized && (q.vote ?? 0) > 0) ||
          (hasEnhanced && q.enhanced);
        return !q.dismissed && matchesType && matchesStatus;
      }

      return !q.dismissed;
    });
  }, [questions, activeFilters, strategicSignalIdSet]);

  const filters: { key: Filter; label: string }[] = [
    { key: "all", label: "All" },
    { key: "question", label: "Questions" },
    { key: "objection", label: "Objections" },
    { key: "observation", label: "Observations" },
    { key: "opportunity", label: "Opportunities" },
    { key: "action_item", label: "Action Items" },
    { key: "starred", label: "Starred" },
    { key: "answered", label: "Answered" },
    { key: "prioritized", label: "Prioritized" },
    { key: "enhanced", label: "Enhanced" },
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
