import { useEffect, useState, type ReactNode } from "react";
import type { Directive, Document, Session, Speaker } from "../../types";
import * as api from "../../services/api";
import DocumentUpload from "./DocumentUpload";
import DirectiveInput from "./DirectiveInput";
import DirectiveList from "./DirectiveList";
import AgentSelector from "./AgentSelector";
import MeetingContextSetup, { MEETING_TYPES } from "./MeetingContextSetup";
import SpeakerSetup from "./SpeakerSetup";
import TranscriptImport from "./TranscriptImport";
import EditableSessionName from "../EditableSessionName";
import InfoTooltip from "../InfoTooltip";

interface Props {
  session: Session;
  directives: Directive[];
  documents: Document[];
  speakers: Speaker[];
  transcriptCount: number;
  processingTranscript?: boolean;
  processingError?: string | null;
  startError?: string | null;
  isStarting?: boolean;
  onStartCall: () => void;
  onOpenVoiceSettings: () => void;
  captureSystemAudio?: boolean;
  onToggleSystemAudio?: (enabled: boolean) => void;
  onProcessTranscript: () => void;
  onRefreshDirectives: () => void;
  onRefreshDocuments: () => void;
  onRefreshSpeakers: () => void;
  onRefreshTranscripts: () => Promise<void>;
  onRenameSession: (name: string) => Promise<void>;
  onUpdateSessionContext: (data: { meeting_type?: Session["meeting_type"]; meeting_context?: string }) => Promise<void>;
}

// One setup step. Collapsed by default when it holds nothing yet, open when
// it does, and the header always says how much is in it, so the page reads
// as a checklist rather than a form.
function SetupSection({
  title,
  summary,
  tooltip,
  defaultOpen,
  optional = false,
  children,
}: {
  title: string;
  summary: string;
  tooltip?: { content: string; details: string[] };
  defaultOpen: boolean;
  optional?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = `precall-${title.toLowerCase().replace(/[^a-z]+/g, "-")}`;
  return (
    <section className="rounded-xl border border-brand-light-gray-1 bg-surface shadow-sm">
      <div className="flex items-center gap-2 px-4 py-3">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={id}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
        >
          <svg
            className={`h-3.5 w-3.5 shrink-0 text-brand-mid-gray transition-transform ${open ? "rotate-90" : ""}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
          <span className="min-w-0">
            <span className="font-display text-sm font-semibold text-brand-dark-gray">
              {title}
              {optional && <span className="ml-1.5 font-body text-[11px] font-normal text-brand-mid-gray">optional</span>}
            </span>
            <span className="block truncate font-body text-xs text-brand-mid-gray">{summary}</span>
          </span>
        </button>
        {tooltip && <InfoTooltip content={tooltip.content} details={tooltip.details} />}
      </div>
      <div id={id} hidden={!open} className="border-t border-brand-light-gray-1 px-4 py-4">
        {children}
      </div>
    </section>
  );
}

function pluralize(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

export default function PreCallView({
  session,
  directives,
  documents,
  speakers,
  transcriptCount,
  processingTranscript = false,
  processingError = null,
  startError = null,
  isStarting = false,
  onStartCall,
  onOpenVoiceSettings,
  captureSystemAudio,
  onToggleSystemAudio,
  onProcessTranscript,
  onRefreshDirectives,
  onRefreshDocuments,
  onRefreshSpeakers,
  onRefreshTranscripts,
  onRenameSession,
  onUpdateSessionContext,
}: Props) {
  const [hasImport, setHasImport] = useState(false);
  const [voiceEnrolled, setVoiceEnrolled] = useState<boolean | null>(null);
  const [showConsent, setShowConsent] = useState(false);
  const hasImportedTranscript = hasImport || transcriptCount > 0;

  useEffect(() => {
    let active = true;
    api.getVoiceProfileStatus()
      .then((status) => {
        if (active) setVoiceEnrolled(status.enrolled);
      })
      .catch((err) => console.error("Failed to load voice profile status", err));
    return () => { active = false; };
  }, []);

  const handleImported = () => {
    setHasImport(true);
    void onRefreshTranscripts();
  };

  const typeLabel = MEETING_TYPES.find((t) => t.value === session.meeting_type)?.label ?? "General";
  const activeDirectives = directives.filter((d) => d.active).length;
  const readiness = [
    typeLabel,
    documents.length ? pluralize(documents.length, "document") : null,
    activeDirectives ? pluralize(activeDirectives, "directive") : null,
    speakers.length ? pluralize(speakers.length, "participant") : "participants auto-detected",
  ].filter(Boolean).join(" · ");

  const soleUserNeedsVoice = speakers.filter((s) => s.is_user).length === 1 && voiceEnrolled === false;
  const error = hasImportedTranscript ? processingError : startError;

  return (
    <div className="mx-auto max-w-3xl px-4 pb-12">
      {/* Action bar: the one thing this screen is for stays in reach while
          the setup below scrolls. */}
      <div className="sticky top-0 z-10 -mx-4 border-b border-brand-light-gray-1 bg-canvas/95 px-4 pb-3 pt-5 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="min-w-0 flex-1">
            <EditableSessionName
              name={session.name}
              onRename={onRenameSession}
              className="text-brand-teal-dark"
            />
            <p className="mt-0.5 truncate font-body text-xs text-brand-mid-gray">{readiness}</p>
          </div>
          {hasImportedTranscript ? (
            <button
              type="button"
              onClick={onProcessTranscript}
              disabled={processingTranscript}
              className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-brand-amber px-5 py-2.5 font-display text-sm font-semibold text-white shadow-md transition-colors hover:bg-amber-600 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-brand-amber focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {processingTranscript ? "Processing..." : "Process Transcript"}
            </button>
          ) : (
            <button
              type="button"
              onClick={onStartCall}
              disabled={isStarting}
              className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-brand-teal px-5 py-2.5 font-display text-sm font-semibold text-white shadow-md transition-colors hover:bg-brand-teal-dark hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-brand-teal-light focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className={`inline-block h-2 w-2 rounded-full ${isStarting ? "animate-pulse bg-white/70" : "bg-white"}`} aria-hidden="true" />
              {isStarting ? "Starting..." : "Start Call"}
            </button>
          )}
        </div>
        {error && (
          <div role="alert" className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 font-body text-sm text-red-700">
            {error}
          </div>
        )}
      </div>

      <div className="mt-5 space-y-3">
        {/* Live-call options and the recording notice sit right under the
            button they qualify; an import has neither. */}
        {!hasImportedTranscript && (
          <div className="rounded-xl border border-brand-light-gray-1 bg-surface p-4 shadow-sm">
            <label className="flex cursor-pointer items-start justify-between gap-4">
              <span className="min-w-0">
                <span className="font-display text-sm font-semibold text-brand-dark-gray">Capture the meeting's audio too</span>
                <span className="mt-0.5 block font-body text-xs leading-relaxed text-brand-mid-gray">
                  Your microphone is always recorded. This adds a second track from the meeting tab,
                  window or screen you pick when the call starts, so remote voices are told apart
                  from yours.
                </span>
              </span>
              <span className="relative mt-0.5 inline-flex shrink-0">
                <input
                  type="checkbox"
                  role="switch"
                  checked={captureSystemAudio ?? false}
                  onChange={(e) => onToggleSystemAudio?.(e.target.checked)}
                  className="peer sr-only"
                />
                <span className="h-6 w-11 rounded-full bg-brand-light-gray-1 transition-colors peer-checked:bg-brand-teal peer-focus-visible:ring-2 peer-focus-visible:ring-brand-teal-light" aria-hidden="true" />
                <span className="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-surface shadow transition-transform peer-checked:translate-x-5" aria-hidden="true" />
              </span>
            </label>
            {captureSystemAudio === false && (
              <p className="mt-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 font-body text-xs text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200">
                Mic-only call: remote participants are transcribed only if your microphone can hear
                them, so with headphones the far end will be missed.
                {soleUserNeedsVoice && (
                  <>
                    {" "}Voice calibration also makes identifying you more reliable.{" "}
                    <button type="button" onClick={onOpenVoiceSettings} className="font-semibold underline">
                      Open Transcription &amp; Audio
                    </button>
                  </>
                )}
              </p>
            )}
            <p className="mt-3 flex flex-wrap items-center gap-x-2 font-body text-xs text-brand-gray">
              <span className="text-brand-amber" aria-hidden="true">&#9888;</span>
              <span>This call is recorded and transcribed. Make sure everyone on it has been told and does not object.</span>
              <button
                type="button"
                onClick={() => setShowConsent((v) => !v)}
                aria-expanded={showConsent}
                className="font-semibold text-brand-teal hover:underline"
              >
                {showConsent ? "Less" : "More"}
              </button>
            </p>
            {showConsent && (
              <p className="mt-2 font-body text-xs leading-relaxed text-brand-mid-gray">
                Backchannel transcribes live audio to generate questions and insights. Before
                starting, ensure all participants have been informed and have given consent (or do
                not object) to the recording and transcription of the conversation. You are
                responsible for compliance with applicable laws and company policies.
              </p>
            )}
          </div>
        )}

        <SetupSection
          title="Context"
          summary={session.meeting_context ? session.meeting_context : "Tell the agents what kind of conversation this is"}
          defaultOpen
          tooltip={{
            content: "Tell the agents what kind of conversation this is so they do not force every session into a client-sales frame.",
            details: [
              "Internal enablement: focus on concepts, misconceptions, learner questions, and follow-up material",
              "Vendor or partner: focus on roadmap, program updates, commitments, and partner motions",
              "Client or delivery: focus on objectives, risks, decisions, opportunities, and next actions",
            ],
          }}
        >
          <MeetingContextSetup session={session} onUpdate={onUpdateSessionContext} />
        </SetupSection>

        <SetupSection
          title="Documents"
          optional
          summary={documents.length ? documents.map((d) => d.filename).join(", ") : "Reference material the agents can draw on"}
          defaultOpen={documents.length > 0}
          tooltip={{
            content: "Upload reference materials before the call. The AI agents will use these documents as context when generating questions and insights.",
            details: [
              "Uploaded files are sent to Gemini for analysis alongside the live transcript",
              "With Privacy First or the PII Shield on, text files are read on this machine instead",
              "Supports PDFs, Word docs, spreadsheets, and text files",
              "Documents persist with the session and can be removed at any time",
            ],
          }}
        >
          <DocumentUpload sessionId={session.id} documents={documents} onRefresh={onRefreshDocuments} />
        </SetupSection>

        <SetupSection
          title="Import a transcript or recording"
          optional
          summary={hasImportedTranscript ? `${transcriptCount || "Imported"} lines ready to process` : "Analyze a past meeting instead of a live call"}
          defaultOpen={hasImportedTranscript}
          tooltip={{
            content: "Instead of a live call, import an existing transcript or audio recording to analyze. The AI agents will process it as if it were a completed call.",
            details: [
              "Transcript files: .txt, .md, .docx - parsed into speaker segments",
              "Audio files: .m4a, .mp3, .wav, .ogg, .flac - transcribed first",
              "After importing, the action button changes to \"Process Transcript\"",
            ],
          }}
        >
          <TranscriptImport sessionId={session.id} onImported={handleImported} />
        </SetupSection>

        <SetupSection
          title="Coaching directives"
          optional
          summary={activeDirectives ? `${pluralize(activeDirectives, "active directive")}` : "What to watch for during this call"}
          defaultOpen={directives.length > 0}
          tooltip={{
            content: "Give the AI specific instructions about what to watch for during the call. Directives shape the questions and insights generated by all agents.",
            details: [
              "Example: \"Capture concepts the sales team struggles with and follow-up questions for the engineer\"",
              "Directives can be toggled on/off without deleting them",
              "Active directives are included in every agent's analysis cycle",
              "You can also add directives mid-call via the active call view",
            ],
          }}
        >
          <div className="space-y-4">
            <DirectiveInput sessionId={session.id} onAdded={onRefreshDirectives} />
            <DirectiveList sessionId={session.id} directives={directives} onRefresh={onRefreshDirectives} />
          </div>
        </SetupSection>

        <SetupSection
          title="Participants"
          optional
          summary={speakers.length ? speakers.map((s) => s.name).join(", ") : "Auto-detected during the call; name them here to label voices"}
          defaultOpen={speakers.length > 0}
          tooltip={{
            content: "Pre-register call participants so the AI can attribute transcript segments to specific speakers by voice. If skipped, speakers are auto-detected and labeled generically.",
            details: [
              "Assign names, roles, and colors to each participant",
              "Mark one speaker as \"me\" to distinguish your voice",
              "Pre-registered speakers improve diarization accuracy",
              "You can still rename auto-detected speakers during or after the call",
            ],
          }}
        >
          <SpeakerSetup sessionId={session.id} speakers={speakers} onRefresh={onRefreshSpeakers} />
        </SetupSection>

        <SetupSection
          title="Agents for this session"
          optional
          summary="Uses the Admin defaults unless you change them here"
          defaultOpen={false}
          tooltip={{
            content: "Enable or disable specific AI agents for this session. Each agent runs independently during the call, analyzing the transcript through a different lens.",
            details: [
              "Consolidated Analyst: questions, observations, opportunities, and action items (periodic, configurable interval)",
              "Principal Agent: quality control, cross-agent synthesis, and strategic pattern detection (event-driven)",
              "Opportunity Specialist: maps relevant client/customer opportunities to the offerings catalog",
              "Audio Bridge: silent listener that enables real-time transcription preview",
              "Changes here override the global Agent Admin defaults for this session only",
            ],
          }}
        >
          <AgentSelector sessionId={session.id} />
        </SetupSection>
      </div>
    </div>
  );
}
