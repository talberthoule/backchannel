import { useState } from "react";
import type { Question, Speaker } from "../../types";
import { presentTypes, typeColor, typeGroupLabel, typeLabel } from "../../utils/insightTypes";

// "all", an item_type slug (built-in or custom lens type), or "dismissed".
// "enhanced" is added only after the session's explicit enhancement pass.
type FilterType = string;

interface QuestionSummaryProps {
  questions: Question[];
  speakers: Speaker[];
  showEnhanced?: boolean;
}

function speakerLabel(speaker: Speaker): string {
  return speaker.display_name && speaker.display_name_enabled ? speaker.display_name : speaker.name;
}

function SummaryCard({ question, speakers, showEnhanced }: { question: Question; speakers: Speaker[]; showEnhanced: boolean }) {
  const itemType = question.item_type || "question";
  const cardColor = typeColor(itemType);
  const attributedSpeaker = question.speaker_id
    ? speakers.find((speaker) => speaker.id === question.speaker_id)
    : null;

  // Subtle bg tint for state emphasis; no colored left border (AI tell).
  const borderStyle = question.needs_followup
    ? "border-brand-amber/30 bg-brand-amber/5"
    : question.answered
      ? "border-green-200 bg-green-50/30"
      : question.starred
        ? "border-brand-amber/30 bg-brand-amber/5"
        : "border-brand-light-gray-1 bg-surface";

  return (
    <div className={`rounded-lg border p-4 ${borderStyle}`}>
      <div className="flex items-start gap-3">
        {/* Star icon */}
        {question.starred && (
          <span className="mt-0.5 text-[#f59e0b]" title="Starred">
            <svg className="h-5 w-5 fill-current" viewBox="0 0 20 20">
              <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.286 3.957a1 1 0 00.95.69h4.162c.969 0 1.371 1.24.588 1.81l-3.37 2.448a1 1 0 00-.364 1.118l1.287 3.957c.3.921-.755 1.688-1.54 1.118l-3.37-2.448a1 1 0 00-1.176 0l-3.37 2.448c-.784.57-1.838-.197-1.539-1.118l1.287-3.957a1 1 0 00-.364-1.118L2.063 9.384c-.783-.57-.38-1.81.588-1.81h4.162a1 1 0 00.95-.69l1.286-3.957z" />
            </svg>
          </span>
        )}
        <div className="flex-1 space-y-2">
          {/* Badges row */}
          <div className="flex items-center gap-2">
            {(itemType !== "question" || (question.lens_label && question.lens_label.trim())) && (
              <span
                className="inline-flex items-center rounded-full px-2 py-0.5 font-body text-xs font-medium text-brand-dark-gray"
                style={{ backgroundColor: `${cardColor}15` }}
              >
                {typeLabel(itemType, question.lens_label)}
              </span>
            )}
            {question.is_followup && (
              <span className="inline-flex items-center rounded-full bg-[#f59e0b]/15 px-2 py-0.5 font-body text-xs font-medium text-[#f59e0b]">
                Follow-up
              </span>
            )}
            {question.answered && (
              <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 font-body text-xs font-medium text-green-700">
                Answered
              </span>
            )}
            {showEnhanced && question.enhanced && (
              <span className="inline-flex items-center rounded-full bg-brand-teal-light/10 px-2 py-0.5 font-body text-xs font-medium text-brand-teal-light">
                Enhanced
              </span>
            )}
            {attributedSpeaker && (
              <span
                className="inline-flex max-w-36 items-center rounded-full px-2 py-0.5 font-body text-xs font-semibold text-white"
                style={{ backgroundColor: attributedSpeaker.color }}
                title={`Attributed to ${speakerLabel(attributedSpeaker)}`}
              >
                <span className="truncate">{speakerLabel(attributedSpeaker)}</span>
              </span>
            )}
            {question.needs_followup && (
              <span className="inline-flex items-center rounded-full bg-[#f59e0b]/20 px-2 py-0.5 font-body text-xs font-medium text-[#f59e0b]">
                Needs Follow-up
              </span>
            )}
          </div>

          <p className="text-sm font-semibold text-brand-dark-gray">{question.question}</p>
          <p className="text-sm text-brand-gray">{question.rationale}</p>

          {question.source_context && (
            <div className="rounded-md bg-brand-light-gray-2 px-3 py-2">
              <p className="text-xs text-brand-mid-gray">
                <span className="font-medium">Context:</span> {question.source_context}
              </p>
            </div>
          )}

          {/* Answer summary */}
          {question.answered && question.answer_summary && (
            <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2">
              <p className="font-body text-sm text-green-800">
                {question.answer_summary}
              </p>
            </div>
          )}

          {/* Follow-up question */}
          {question.needs_followup && question.followup_question && (
            <div className="rounded-md border border-[#f59e0b]/30 bg-[#f59e0b]/10 px-3 py-2">
              <p className="font-body text-xs font-medium text-[#f59e0b]">Follow-up question:</p>
              <p className="mt-0.5 font-body text-sm text-brand-dark-gray">
                {question.followup_question}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SectionHeader({ label, color, count }: { label: string; color: string; count: number }) {
  return (
    <h3 className="flex items-center gap-2 font-display text-sm font-semibold uppercase tracking-wide text-brand-dark-gray">
      <span
        className="inline-block h-3 w-3 rounded-full"
        style={{ backgroundColor: color }}
      />
      {label}
      <span className="rounded-full px-2 py-0.5 text-xs font-medium text-brand-dark-gray" style={{ backgroundColor: `${color}15` }}>
        {count}
      </span>
    </h3>
  );
}

// One accent (teal) for the active card; every other metric stays neutral
// slate with a small leading category dot. Numbers are tabular so counts align.
function StatCard({
  label,
  count,
  dotColor,
  isActive,
  onClick,
}: {
  label: string;
  count: number;
  dotColor?: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 rounded-lg border px-5 py-4 text-left transition-colors ${
        isActive
          ? "border-brand-teal bg-brand-teal/5 ring-1 ring-brand-teal"
          : "border-brand-light-gray-1 bg-surface hover:bg-brand-light-gray-2/50"
      }`}
    >
      <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-brand-mid-gray">
        {dotColor && (
          <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: dotColor }} />
        )}
        {label}
      </p>
      <p className={`mt-1 font-display text-2xl font-bold tabular-nums ${isActive ? "text-brand-teal" : "text-brand-dark-gray"}`}>
        {count}
      </p>
    </button>
  );
}

export default function QuestionSummary({ questions, speakers, showEnhanced = false }: QuestionSummaryProps) {
  const [showDismissed, setShowDismissed] = useState(false);
  const [filter, setFilter] = useState<FilterType>("all");

  // Separate dismissed first
  const dismissed = questions.filter((q) => q.dismissed);
  const active = questions.filter((q) => !q.dismissed);
  const enhanced = showEnhanced ? active.filter((q) => q.enhanced) : [];
  const visibleActive = filter === "enhanced" ? enhanced : active;

  // Dynamic type groups: built-ins in fixed order, then custom lens types
  const types = presentTypes(active);
  const byType = (list: Question[], t: string) =>
    list.filter((q) => (q.item_type || "question") === t);

  const questionItems = byType(visibleActive, "question");

  // Sub-groups within questions
  const qNeedsFollowup = questionItems.filter((q) => q.needs_followup);
  const qStarred = questionItems.filter((q) => q.starred && !q.needs_followup);
  const qAnswered = questionItems.filter((q) => q.answered && !q.starred && !q.needs_followup);
  const qUnanswered = questionItems.filter((q) => !q.answered && !q.starred && !q.needs_followup);

  const handleFilterClick = (type: FilterType) => {
    setFilter(filter === type ? "all" : type);
  };

  // Determine what sections to show based on filter
  const showType = (t: string) => filter === "all" || filter === t || filter === "enhanced";
  const sectionTypes = types.filter((t) => t !== "question");
  const showQuestions = showType("question");
  const showDismissedSection = filter === "all" || filter === "dismissed";
  const filteredEmpty =
    filter !== "all" &&
    filter !== "dismissed" &&
    (filter === "enhanced" ? enhanced.length === 0 : byType(visibleActive, filter).length === 0);

  return (
    <div className="space-y-6">
      {/* Stats bar — clickable to filter */}
      <div className="flex gap-4">
        <StatCard
          label="Total"
          count={questions.length}
          isActive={filter === "all"}
          onClick={() => setFilter("all")}
        />
        {types.map((t) => {
          const items = byType(active, t);
          return (
            <StatCard
              key={t}
              label={typeGroupLabel(t, items)}
              count={items.length}
              dotColor={typeColor(t)}
              isActive={filter === t}
              onClick={() => handleFilterClick(t)}
            />
          );
        })}
        {showEnhanced && (
          <StatCard
            label="Enhanced"
            count={enhanced.length}
            dotColor={typeColor("question")}
            isActive={filter === "enhanced"}
            onClick={() => handleFilterClick("enhanced")}
          />
        )}
      </div>

      {/* Typed sections (built-ins first, then custom lens types); the
          question section renders last with its status sub-groups */}
      {sectionTypes.map((t) => {
        const items = byType(visibleActive, t);
        if (!showType(t) || items.length === 0) return null;
        return (
          <section key={t} className="space-y-3">
            <SectionHeader label={typeGroupLabel(t, items)} color={typeColor(t)} count={items.length} />
            {items.map((q) => (
              <SummaryCard key={q.id} question={q} speakers={speakers} showEnhanced={showEnhanced} />
            ))}
          </section>
        );
      })}

      {/* Questions with sub-groups */}
      {showQuestions && questionItems.length > 0 && (
        <section className="space-y-4">
          <SectionHeader label={typeGroupLabel("question", questionItems)} color={typeColor("question")} count={questionItems.length} />

          {qNeedsFollowup.length > 0 && (
            <div className="space-y-3">
              <h4 className="font-display text-xs font-semibold uppercase tracking-wide text-[#f59e0b]">
                Needs Follow-up
              </h4>
              {qNeedsFollowup.map((q) => (
                <SummaryCard key={q.id} question={q} speakers={speakers} showEnhanced={showEnhanced} />
              ))}
            </div>
          )}

          {qStarred.length > 0 && (
            <div className="space-y-3">
              <h4 className="font-display text-xs font-semibold uppercase tracking-wide text-[#f59e0b]">
                Starred
              </h4>
              {qStarred.map((q) => (
                <SummaryCard key={q.id} question={q} speakers={speakers} showEnhanced={showEnhanced} />
              ))}
            </div>
          )}

          {qAnswered.length > 0 && (
            <div className="space-y-3">
              <h4 className="font-display text-xs font-semibold uppercase tracking-wide text-green-600">
                Answered
              </h4>
              {qAnswered.map((q) => (
                <SummaryCard key={q.id} question={q} speakers={speakers} showEnhanced={showEnhanced} />
              ))}
            </div>
          )}

          {qUnanswered.length > 0 && (
            <div className="space-y-3">
              <h4 className="font-display text-xs font-semibold uppercase tracking-wide text-brand-gray">
                Unanswered
              </h4>
              {qUnanswered.map((q) => (
                <SummaryCard key={q.id} question={q} speakers={speakers} showEnhanced={showEnhanced} />
              ))}
            </div>
          )}
        </section>
      )}

      {/* Dismissed (collapsed) */}
      {showDismissedSection && dismissed.length > 0 && (
        <section>
          <button
            onClick={() => setShowDismissed(!showDismissed)}
            className="flex items-center gap-2 text-sm font-medium text-brand-mid-gray transition-colors hover:text-brand-gray"
          >
            <svg
              className={`h-4 w-4 transition-transform ${showDismissed ? "rotate-90" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            Dismissed ({dismissed.length})
          </button>

          {showDismissed && (
            <div className="mt-3 space-y-3 opacity-60">
              {dismissed.map((q) => (
                <SummaryCard key={q.id} question={q} speakers={speakers} showEnhanced={showEnhanced} />
              ))}
            </div>
          )}
        </section>
      )}

      {/* Empty state */}
      {questions.length === 0 && (
        <div className="rounded-xl bg-surface p-10 text-center shadow-sm">
          <p className="text-brand-mid-gray">No insights were generated during this session.</p>
        </div>
      )}

      {/* Filtered empty state */}
      {questions.length > 0 && filteredEmpty && (
        <div className="rounded-xl bg-surface p-10 text-center shadow-sm">
          <p className="text-brand-mid-gray">
            No {filter === "enhanced" ? "enhanced items" : typeGroupLabel(filter, byType(active, filter)).toLowerCase()} were captured during this session.
          </p>
        </div>
      )}
    </div>
  );
}
