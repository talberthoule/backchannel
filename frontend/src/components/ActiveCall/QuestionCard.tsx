import { useState } from "react";
import type { Question, Speaker } from "../../types";
import { typeColor, typeLabel } from "../../utils/insightTypes";

const AGENT_LABELS: Record<string, string> = {
  question_hunter: "Question Hunter",
  observer: "Observer",
  opportunity_scout: "Opp. Scout",
  action_tracker: "Action Tracker",
  synthesizer: "Synthesizer",
  refiner: "Refiner",
  opportunity_specialist: "Opp. Specialist",
  consolidated_analyst: "Analyst",
  objection_handler: "Objection Handler",
  general: "General",
};

interface QuestionCardProps {
  question: Question;
  speakers: Speaker[];
  isStrategicSignal?: boolean;
  onStar: (starred: boolean) => void;
  onDismiss: () => void;
  onVote: (vote: number) => void;
}

function speakerLabel(speaker: Speaker): string {
  return speaker.display_name && speaker.display_name_enabled ? speaker.display_name : speaker.name;
}

export default function QuestionCard({ question, speakers, isStrategicSignal = false, onStar, onDismiss, onVote }: QuestionCardProps) {
  const [dismissing, setDismissing] = useState(false);
  const [showEnrichment, setShowEnrichment] = useState(false);
  const currentVote = question.vote ?? 0;

  function handleDismiss() {
    setDismissing(true);
    setTimeout(() => onDismiss(), 300);
  }

  const itemType = question.item_type || "question";
  const badgeColor = typeColor(itemType);
  const badgeLabel = typeLabel(itemType, question.lens_label);
  const isRefined = (question.revision_count ?? 0) > 0;
  const surfacedAt = formatTimestamp(question.created_at);
  const attributedSpeaker = question.speaker_id
    ? speakers.find((speaker) => speaker.id === question.speaker_id)
    : null;

  return (
    <div
      className={`animate-slide-in-right rounded-lg border border-brand-light-gray-1 p-4 transition duration-300 ${
        isStrategicSignal ? "bg-brand-teal/5 shadow-md ring-2 ring-brand-teal/25" : "bg-surface shadow-sm"
      } ${
        dismissing ? "translate-x-4 opacity-0" : ""
      } ${question.dismissed ? "opacity-40" : ""} ${
        isRefined && !isStrategicSignal ? "ring-1 ring-inset ring-brand-teal-light/20" : ""
      }`}
    >
      {/* Top row: badges + actions */}
      <div className="mb-2 flex items-start justify-between">
        <div className="flex flex-wrap items-center gap-1.5">
          {question.is_followup && (
            <span className="inline-flex items-center rounded-full bg-[#f59e0b]/15 px-2 py-0.5 font-body text-xs font-medium text-[#f59e0b]">
              Follow-up
            </span>
          )}
          {question.directive_id && (
            <span className="inline-flex items-center rounded-full bg-[#f59e0b]/15 px-2 py-0.5 font-body text-xs font-medium text-[#f59e0b]">
              Directive
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
          {isStrategicSignal && (
            <span className="inline-flex items-center rounded-full bg-brand-teal/10 px-2 py-0.5 font-body text-xs font-semibold text-brand-teal">
              Strategic Signal
            </span>
          )}
          {/* Refined badge */}
          {isRefined && (
            <button
              onClick={() => setShowEnrichment((v) => !v)}
              className="inline-flex items-center gap-1 rounded-full bg-brand-teal-light/10 px-2 py-0.5 font-body text-xs font-medium text-brand-teal-light transition-colors hover:bg-brand-teal-light/20"
              title="This insight was refined by the analysis engine"
            >
              <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182" />
              </svg>
              Refined{(question.revision_count ?? 0) > 1 ? ` x${question.revision_count}` : ""}
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-end gap-1">
          <span
            className="font-mono text-[11px] text-brand-mid-gray"
            title={formatFullTimestamp(question.created_at)}
          >
            {surfacedAt}
          </span>

          {/* Agent source badge */}
          {question.agent_source && question.agent_source !== "general" && (
            <span className="inline-flex items-center rounded-full bg-brand-light-gray-2 px-2 py-0.5 font-body text-[10px] font-medium text-brand-mid-gray">
              {AGENT_LABELS[question.agent_source] || question.agent_source}
            </span>
          )}

          {attributedSpeaker && (
            <span
              className="inline-flex max-w-32 items-center rounded-full px-2 py-0.5 font-body text-[10px] font-semibold text-white"
              style={{ backgroundColor: attributedSpeaker.color }}
              title={`Attributed to ${speakerLabel(attributedSpeaker)}`}
            >
              <span className="truncate">{speakerLabel(attributedSpeaker)}</span>
            </span>
          )}

          {/* Type badge — shows the producing lens's heading when available */}
          {(itemType !== "question" || (question.lens_label && question.lens_label.trim())) && (
            <span
              className="inline-flex items-center rounded-full px-2 py-0.5 font-body text-xs font-medium"
              style={{ backgroundColor: `${badgeColor}15`, color: badgeColor }}
            >
              {badgeLabel}
            </span>
          )}
        </div>
      </div>

      {/* Question text */}
      <p className="font-body text-base font-medium leading-snug text-brand-dark-gray">
        {question.question}
      </p>

      {/* Rationale */}
      {question.rationale && (
        <p className="mt-2 font-body text-sm leading-relaxed text-brand-gray">
          {question.rationale}
        </p>
      )}

      {/* Source context */}
      {question.source_context && (
        <blockquote className="mt-3 border-l-2 border-brand-light-gray-1 pl-3 font-body text-xs italic text-brand-mid-gray">
          {question.source_context}
        </blockquote>
      )}

      {/* Offering match (for opportunities) */}
      {question.offering_match && (
        <div className="mt-3 rounded-md border border-[#10b981]/30 bg-[#10b981]/5 px-3 py-2">
          <div className="flex items-center gap-1.5 mb-1">
            <svg className="h-3.5 w-3.5 text-[#10b981]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244" />
            </svg>
            <span className="font-display text-xs font-semibold text-[#10b981]">Offering Match</span>
          </div>
          <p className="font-body text-xs leading-relaxed text-brand-gray">{question.offering_match}</p>
        </div>
      )}

      {/* Enrichment notes (collapsible) */}
      {isRefined && showEnrichment && question.enrichment_notes && (
        <div className="mt-3 rounded-md border border-brand-teal-light/20 bg-brand-teal-light/5 px-3 py-2">
          <div className="flex items-center gap-1.5 mb-1">
            <svg className="h-3.5 w-3.5 text-brand-teal-light" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 0 0-2.455 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z" />
            </svg>
            <span className="font-display text-xs font-semibold text-brand-teal-light">Refinement Notes</span>
          </div>
          {question.enrichment_notes.split("\n").map((note, i) => (
            <p key={i} className="font-body text-xs leading-relaxed text-brand-gray">
              {note}
            </p>
          ))}
        </div>
      )}

      {/* Answer summary (shown when answered) */}
      {question.answered && question.answer_summary && (
        <div className="mt-3 rounded-md border border-green-200 bg-green-50 px-3 py-2">
          <p className="font-body text-sm text-green-800">
            {question.answer_summary}
          </p>
        </div>
      )}

      {/* Follow-up needed badge and question */}
      {question.answered && question.needs_followup && (
        <div className="mt-3 rounded-md border border-[#f59e0b]/30 bg-[#f59e0b]/10 px-3 py-2">
          <span className="inline-flex items-center rounded-full bg-[#f59e0b]/20 px-2 py-0.5 font-body text-xs font-medium text-[#f59e0b]">
            Needs Follow-up
          </span>
          {question.followup_question && (
            <p className="mt-1 font-body text-sm text-brand-dark-gray">
              {question.followup_question}
            </p>
          )}
        </div>
      )}

      {/* Actions row */}
      <div className="mt-3 flex items-center justify-end gap-0.5">
          <button
            onClick={() => onVote(currentVote === 1 ? 0 : 1)}
            className={`rounded p-1 transition-colors hover:bg-brand-light-gray-2 hover:text-brand-teal ${
              currentVote > 0 ? "bg-brand-teal/10 text-brand-teal" : "text-brand-mid-gray"
            }`}
            title="Upvote insight"
            aria-label="Upvote insight"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 15.75 7.5-7.5 7.5 7.5" />
            </svg>
          </button>
          {currentVote !== 0 && (
            <span
              className={`min-w-[1.25rem] text-center font-mono text-xs font-semibold ${
                currentVote > 0 ? "text-brand-teal" : "text-brand-mid-gray"
              }`}
              title={`Vote: ${currentVote}`}
            >
              {currentVote > 0 ? `+${currentVote}` : currentVote}
            </span>
          )}
          <button
            onClick={() => onVote(currentVote === -1 ? 0 : -1)}
            className={`rounded p-1 transition-colors hover:bg-brand-light-gray-2 hover:text-red-500 ${
              currentVote < 0 ? "bg-red-50 text-red-500" : "text-brand-mid-gray"
            }`}
            title="Downvote insight"
            aria-label="Downvote insight"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
            </svg>
          </button>

          {/* Star button */}
          <button
            onClick={() => onStar(!question.starred)}
            className="rounded p-1 transition-colors hover:bg-brand-light-gray-2"
            aria-label={question.starred ? "Unstar" : "Star"}
          >
            {question.starred ? (
              <svg className="h-4 w-4 text-[#f59e0b]" fill="currentColor" viewBox="0 0 20 20">
                <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
              </svg>
            ) : (
              <svg className="h-4 w-4 text-brand-mid-gray" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.562.562 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.562.562 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
              </svg>
            )}
          </button>

          {/* Dismiss button */}
          <button
            onClick={handleDismiss}
            className="rounded p-1 text-brand-mid-gray transition-colors hover:bg-red-50 hover:text-red-500"
            aria-label="Dismiss"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
      </div>
    </div>
  );
}

function formatTimestamp(ts: string): string {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return "--:--";

  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatFullTimestamp(ts: string): string {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;

  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
