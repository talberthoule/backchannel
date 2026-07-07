import React, { useState } from "react";
import type { Question, Speaker } from "../../types";

const TYPE_CONFIG: Record<string, { label: string; color: string }> = {
  question: { label: "Questions", color: "#0d9488" },
  objection: { label: "Objections", color: "#f59e0b" },
  observation: { label: "Observations", color: "#7c3aed" },
  opportunity: { label: "Opportunities", color: "#10b981" },
  action_item: { label: "Action Items", color: "#e2231a" },
};

type FilterType = "all" | "action_item" | "objection" | "opportunity" | "observation" | "question" | "enhanced" | "dismissed";

interface QuestionSummaryProps {
  questions: Question[];
  speakers: Speaker[];
}

function speakerLabel(speaker: Speaker): string {
  return speaker.display_name && speaker.display_name_enabled ? speaker.display_name : speaker.name;
}

function SummaryCard({ question, speakers }: { question: Question; speakers: Speaker[] }) {
  const typeConfig = TYPE_CONFIG[question.item_type] || TYPE_CONFIG.question;
  const attributedSpeaker = question.speaker_id
    ? speakers.find((speaker) => speaker.id === question.speaker_id)
    : null;

  // Determine border style based on state
  const borderStyle = question.needs_followup
    ? "border-[#f59e0b]/30 bg-[#f59e0b]/5"
    : question.answered
      ? "border-green-200 bg-green-50/30"
      : question.starred
        ? "border-[#f59e0b]/30 bg-[#f59e0b]/5"
        : "border-brand-light-gray-1 bg-white";

  return (
    <div
      className={`rounded-lg border border-l-4 p-4 ${borderStyle}`}
      style={{ borderLeftColor: typeConfig.color }}
    >
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
            {question.item_type && question.item_type !== "question" && (
              <span
                className="inline-flex items-center rounded-full px-2 py-0.5 font-body text-xs font-medium"
                style={{ backgroundColor: `${typeConfig.color}15`, color: typeConfig.color }}
              >
                {TYPE_CONFIG[question.item_type]?.label?.replace(/s$/, "") || "Question"}
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
            {question.enhanced && (
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
              <p className="mt-0.5 font-body text-sm text-[#333]">
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
    <h3 className="flex items-center gap-2 font-display text-sm font-semibold uppercase tracking-wide" style={{ color }}>
      <span
        className="inline-block h-3 w-3 rounded-full"
        style={{ backgroundColor: color }}
      />
      {label}
      <span className="rounded-full px-2 py-0.5 text-xs font-medium" style={{ backgroundColor: `${color}15`, color }}>
        {count}
      </span>
    </h3>
  );
}

function StatCard({
  label,
  count,
  color,
  isActive,
  onClick,
}: {
  label: string;
  count: number;
  color: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 rounded-xl px-5 py-4 shadow-sm text-left transition-all bg-white ${
        isActive
          ? "ring-offset-1"
          : "hover:bg-brand-light-gray-2/50"
      }`}
      style={isActive ? { boxShadow: `0 0 0 2px ${color}` } : undefined}
    >
      <p className="text-xs font-medium uppercase tracking-wide" style={{ color }}>
        {label}
      </p>
      <p className="mt-1 font-display text-2xl font-bold" style={{ color }}>
        {count}
      </p>
    </button>
  );
}

export default function QuestionSummary({ questions, speakers }: QuestionSummaryProps) {
  const [showDismissed, setShowDismissed] = useState(false);
  const [filter, setFilter] = useState<FilterType>("all");

  // Separate dismissed first
  const dismissed = questions.filter((q) => q.dismissed);
  const active = questions.filter((q) => !q.dismissed);
  const enhanced = active.filter((q) => q.enhanced);
  const visibleActive = filter === "enhanced" ? enhanced : active;
  const allActionItems = active.filter((q) => q.item_type === "action_item");
  const allObjections = active.filter((q) => q.item_type === "objection");
  const allOpportunities = active.filter((q) => q.item_type === "opportunity");
  const allObservations = active.filter((q) => q.item_type === "observation");
  const allQuestionItems = active.filter((q) => q.item_type === "question" || !q.item_type);

  // Group by item type
  const actionItems = visibleActive.filter((q) => q.item_type === "action_item");
  const objections = visibleActive.filter((q) => q.item_type === "objection");
  const opportunities = visibleActive.filter((q) => q.item_type === "opportunity");
  const observations = visibleActive.filter((q) => q.item_type === "observation");
  const questionItems = visibleActive.filter((q) => q.item_type === "question" || !q.item_type);

  // Sub-groups within questions
  const qNeedsFollowup = questionItems.filter((q) => q.needs_followup);
  const qStarred = questionItems.filter((q) => q.starred && !q.needs_followup);
  const qAnswered = questionItems.filter((q) => q.answered && !q.starred && !q.needs_followup);
  const qUnanswered = questionItems.filter((q) => !q.answered && !q.starred && !q.needs_followup);

  const handleFilterClick = (type: FilterType) => {
    setFilter(filter === type ? "all" : type);
  };

  // Determine what sections to show based on filter
  const showActionItems = filter === "all" || filter === "action_item" || filter === "enhanced";
  const showObjections = filter === "all" || filter === "objection" || filter === "enhanced";
  const showOpportunities = filter === "all" || filter === "opportunity" || filter === "enhanced";
  const showObservations = filter === "all" || filter === "observation" || filter === "enhanced";
  const showQuestions = filter === "all" || filter === "question" || filter === "enhanced";
  const showDismissedSection = filter === "all" || filter === "dismissed";

  return (
    <div className="space-y-6">
      {/* Stats bar — clickable to filter */}
      <div className="flex gap-4">
        <StatCard
          label="Total"
          count={questions.length}
          color={filter === "all" ? "#333" : "#999"}
          isActive={filter === "all"}
          onClick={() => setFilter("all")}
        />
        <StatCard
          label="Action Items"
          count={allActionItems.length}
          color="#e2231a"
          isActive={filter === "action_item"}
          onClick={() => handleFilterClick("action_item")}
        />
        <StatCard
          label="Objections"
          count={allObjections.length}
          color="#f59e0b"
          isActive={filter === "objection"}
          onClick={() => handleFilterClick("objection")}
        />
        <StatCard
          label="Opportunities"
          count={allOpportunities.length}
          color="#10b981"
          isActive={filter === "opportunity"}
          onClick={() => handleFilterClick("opportunity")}
        />
        <StatCard
          label="Observations"
          count={allObservations.length}
          color="#7c3aed"
          isActive={filter === "observation"}
          onClick={() => handleFilterClick("observation")}
        />
        <StatCard
          label="Questions"
          count={allQuestionItems.length}
          color="#0d9488"
          isActive={filter === "question"}
          onClick={() => handleFilterClick("question")}
        />
        <StatCard
          label="Enhanced"
          count={enhanced.length}
          color="#2dd4bf"
          isActive={filter === "enhanced"}
          onClick={() => handleFilterClick("enhanced")}
        />
      </div>

      {/* Action Items (top priority) */}
      {showActionItems && actionItems.length > 0 && (
        <section className="space-y-3">
          <SectionHeader label="Action Items" color="#e2231a" count={actionItems.length} />
          {actionItems.map((q) => (
            <SummaryCard key={q.id} question={q} speakers={speakers} />
          ))}
        </section>
      )}

      {/* Objections */}
      {showObjections && objections.length > 0 && (
        <section className="space-y-3">
          <SectionHeader label="Objections" color="#f59e0b" count={objections.length} />
          {objections.map((q) => (
            <SummaryCard key={q.id} question={q} speakers={speakers} />
          ))}
        </section>
      )}

      {/* Opportunities */}
      {showOpportunities && opportunities.length > 0 && (
        <section className="space-y-3">
          <SectionHeader label="Opportunities" color="#10b981" count={opportunities.length} />
          {opportunities.map((q) => (
            <SummaryCard key={q.id} question={q} speakers={speakers} />
          ))}
        </section>
      )}

      {/* Observations */}
      {showObservations && observations.length > 0 && (
        <section className="space-y-3">
          <SectionHeader label="Observations" color="#7c3aed" count={observations.length} />
          {observations.map((q) => (
            <SummaryCard key={q.id} question={q} speakers={speakers} />
          ))}
        </section>
      )}

      {/* Questions with sub-groups */}
      {showQuestions && questionItems.length > 0 && (
        <section className="space-y-4">
          <SectionHeader label="Questions" color="#0d9488" count={questionItems.length} />

          {qNeedsFollowup.length > 0 && (
            <div className="space-y-3">
              <h4 className="font-display text-xs font-semibold uppercase tracking-wide text-[#f59e0b]">
                Needs Follow-up
              </h4>
              {qNeedsFollowup.map((q) => (
                <SummaryCard key={q.id} question={q} speakers={speakers} />
              ))}
            </div>
          )}

          {qStarred.length > 0 && (
            <div className="space-y-3">
              <h4 className="font-display text-xs font-semibold uppercase tracking-wide text-[#f59e0b]">
                Starred
              </h4>
              {qStarred.map((q) => (
                <SummaryCard key={q.id} question={q} speakers={speakers} />
              ))}
            </div>
          )}

          {qAnswered.length > 0 && (
            <div className="space-y-3">
              <h4 className="font-display text-xs font-semibold uppercase tracking-wide text-green-600">
                Answered
              </h4>
              {qAnswered.map((q) => (
                <SummaryCard key={q.id} question={q} speakers={speakers} />
              ))}
            </div>
          )}

          {qUnanswered.length > 0 && (
            <div className="space-y-3">
              <h4 className="font-display text-xs font-semibold uppercase tracking-wide text-brand-gray">
                Unanswered
              </h4>
              {qUnanswered.map((q) => (
                <SummaryCard key={q.id} question={q} speakers={speakers} />
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
                <SummaryCard key={q.id} question={q} speakers={speakers} />
              ))}
            </div>
          )}
        </section>
      )}

      {/* Empty state */}
      {questions.length === 0 && (
        <div className="rounded-xl bg-white p-10 text-center shadow-sm">
          <p className="text-brand-mid-gray">No insights were generated during this session.</p>
        </div>
      )}

      {/* Filtered empty state */}
      {filter !== "all" && questions.length > 0 && (
        (filter === "action_item" && actionItems.length === 0) ||
        (filter === "objection" && objections.length === 0) ||
        (filter === "opportunity" && opportunities.length === 0) ||
        (filter === "observation" && observations.length === 0) ||
        (filter === "question" && questionItems.length === 0) ||
        (filter === "enhanced" && enhanced.length === 0)
      ) && (
        <div className="rounded-xl bg-white p-10 text-center shadow-sm">
          <p className="text-brand-mid-gray">
            No {TYPE_CONFIG[filter]?.label?.toLowerCase() || "items"} were captured during this session.
          </p>
        </div>
      )}
    </div>
  );
}
