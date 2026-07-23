import { useEffect, useState } from "react";
import type { Directive, Document, Session, Speaker } from "../../types";
import * as api from "../../services/api";
import DocumentUpload from "./DocumentUpload";
import DirectiveInput from "./DirectiveInput";
import DirectiveList from "./DirectiveList";
import AgentSelector from "./AgentSelector";
import MeetingContextSetup from "./MeetingContextSetup";
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

export default function PreCallView({
  session,
  directives,
  documents,
  speakers,
  transcriptCount,
  processingTranscript = false,
  processingError = null,
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
  const [showSpeakers, setShowSpeakers] = useState(false);
  const [showAgents, setShowAgents] = useState(false);
  const [hasImport, setHasImport] = useState(false);
  const [voiceEnrolled, setVoiceEnrolled] = useState<boolean | null>(null);
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

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      {/* Session header */}
      <div>
        <EditableSessionName
          name={session.name}
          onRename={onRenameSession}
          className="text-brand-teal-dark"
        />
        <p className="font-body text-sm text-brand-gray mt-1">
          Set the conversation context, documents, and coaching directives before starting.
        </p>
      </div>

      {/* Meeting context */}
      <section className="space-y-3">
        <h2 className="font-display text-lg font-semibold text-brand-dark-gray flex items-center gap-2">
          Meeting Context
          <InfoTooltip
            content="Tell the agents what kind of conversation this is so they do not force every session into a client-sales frame."
            details={[
              "Internal enablement: focus on concepts, misconceptions, learner questions, and follow-up material",
              "Vendor or partner: focus on roadmap, program updates, commitments, and partner motions",
              "Client or delivery: focus on objectives, risks, decisions, opportunities, and next actions",
            ]}
          />
        </h2>
        <MeetingContextSetup session={session} onUpdate={onUpdateSessionContext} />
      </section>

      {/* Documents section */}
      <section className="space-y-3">
        <h2 className="font-display text-lg font-semibold text-brand-dark-gray flex items-center gap-2">
          Documents
          <InfoTooltip
            content="Upload reference materials before the call. The AI agents will use these documents as context when generating questions and insights."
            details={[
              "Uploaded files are sent to Gemini for analysis alongside the live transcript",
              "Supports PDFs, Word docs, spreadsheets, and text files",
              "Documents persist with the session and can be removed at any time",
              "Unavailable in Privacy First mode, since files would leave this machine",
            ]}
          />
        </h2>
        <DocumentUpload
          sessionId={session.id}
          documents={documents}
          onRefresh={onRefreshDocuments}
        />
      </section>

      {/* Import existing transcript or audio */}
      <section className="space-y-3">
        <h2 className="font-display text-lg font-semibold text-brand-dark-gray flex items-center gap-2">
          Import Transcript
          <InfoTooltip
            content="Instead of a live call, import an existing transcript or audio recording to analyze. The AI agents will process it as if it were a completed call."
            details={[
              "Transcript files: .txt, .md, .docx — parsed into speaker segments",
              "Audio files: .m4a, .mp3, .wav, .ogg, .flac — transcribed by Gemini first",
              "After importing, the action button changes to \"Process Transcript\"",
            ]}
          />
        </h2>
        <TranscriptImport sessionId={session.id} onImported={handleImported} />
      </section>

      {/* Directives section */}
      <section className="space-y-4">
        <h2 className="font-display text-lg font-semibold text-brand-dark-gray flex items-center gap-2">
          Coaching Directives
          <InfoTooltip
            content="Give the AI specific instructions about what to watch for during the call. Directives shape the questions and insights generated by all agents."
            details={[
              "Example: \"Capture concepts the sales team struggles with and follow-up questions for the engineer\"",
              "Directives can be toggled on/off without deleting them",
              "Active directives are included in every agent's analysis cycle",
              "You can also add directives mid-call via the active call view",
            ]}
          />
        </h2>
        <DirectiveInput sessionId={session.id} onAdded={onRefreshDirectives} />
        <DirectiveList
          sessionId={session.id}
          directives={directives}
          onRefresh={onRefreshDirectives}
        />
      </section>

      {/* Optional: Call Participants */}
      <section className="space-y-3">
        <button
          onClick={() => setShowSpeakers(!showSpeakers)}
          className="flex items-center gap-2 font-display text-lg font-semibold text-brand-dark-gray"
        >
          <span className={`text-sm transition-transform ${showSpeakers ? "rotate-90" : ""}`}>&#9654;</span>
          Call Participants
          <span className="text-sm font-normal text-brand-mid-gray">(Optional)</span>
          <span onClick={(e) => e.stopPropagation()}>
            <InfoTooltip
              content="Pre-register call participants so the AI can attribute transcript segments to specific speakers by voice. If skipped, speakers are auto-detected and labeled generically."
              details={[
                "Assign names, roles, and colors to each participant",
                "Mark one speaker as \"me\" to distinguish your voice",
                "Pre-registered speakers improve diarization accuracy",
                "You can still rename auto-detected speakers during or after the call",
              ]}
            />
          </span>
        </button>
        {!showSpeakers && speakers.length === 0 && (
          <p className="text-sm text-brand-mid-gray ml-6">
            Speakers will be auto-detected during the call. Set up participants here to customize names and colors.
          </p>
        )}
        {(showSpeakers || speakers.length > 0) && (
          <SpeakerSetup sessionId={session.id} speakers={speakers} onRefresh={onRefreshSpeakers} />
        )}
      </section>

      {/* Agent Selection */}
      <section className="space-y-3">
        <button
          onClick={() => setShowAgents?.(!showAgents)}
          className="flex items-center gap-2 font-display text-sm font-semibold uppercase tracking-wide text-brand-teal"
        >
          <svg className={`h-3.5 w-3.5 transition-transform ${showAgents ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
          Agent Selection
          <span className="font-body text-[10px] font-normal normal-case tracking-normal text-brand-mid-gray">(Optional)</span>
          <span onClick={(e) => e.stopPropagation()}>
            <InfoTooltip
              content="Enable or disable specific AI agents for this session. Each agent runs independently during the call, analyzing the transcript through a different lens."
              details={[
                "Consolidated Analyst: questions, observations, opportunities, and action items (periodic, configurable interval)",
                "Principal Agent: quality control, cross-agent synthesis, and strategic pattern detection (event-driven)",
                "Opportunity Specialist: maps relevant client/customer opportunities to the offerings catalog",
                "Audio Bridge: silent listener that enables real-time transcription preview",
                "Changes here override the global Agent Admin defaults for this session only",
              ]}
            />
          </span>
        </button>
        {showAgents && <AgentSelector sessionId={session.id} />}
      </section>

      {/* Consent notice — only show for live calls */}
      {!hasImportedTranscript && (
        <div className="rounded-lg border border-brand-amber/40 bg-orange-50/60 p-4">
          <div className="flex gap-3">
            <span className="text-brand-amber text-lg leading-none mt-0.5">&#9888;</span>
            <div>
              <p className="font-display text-sm font-semibold text-brand-dark-gray">
                Recording & Transcription Notice
              </p>
              <p className="font-body text-sm text-brand-gray mt-1 leading-relaxed">
                This tool transcribes live audio to generate questions. Before starting,
                ensure all call participants have been informed and have given consent
                (or do not object) to the recording and transcription of the conversation.
                You are responsible for compliance with applicable laws and company policies.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Action button — changes based on whether a transcript was imported */}
      <div className="pt-4">
        {hasImportedTranscript ? (
          <div className="space-y-3">
            {processingError && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 font-body text-sm text-red-700">
                {processingError}
              </div>
            )}
            <button
              onClick={onProcessTranscript}
              disabled={processingTranscript}
              className="w-full py-3 rounded-lg font-display font-semibold text-white text-lg
                         bg-brand-amber hover:bg-amber-600 transition-colors
                         shadow-md hover:shadow-lg focus:ring-2
                         focus:ring-brand-amber focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {processingTranscript ? "Processing..." : "Process Transcript"}
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={captureSystemAudio}
                onChange={(e) => onToggleSystemAudio?.(e.target.checked)}
                className="h-4 w-4 rounded border-brand-light-gray-1 text-brand-teal"
              />
              <span className="font-body text-sm text-brand-dark-gray">
                Capture meeting audio (share a tab or screen with audio)
              </span>
            </label>
            {captureSystemAudio === false
              && speakers.filter((speaker) => speaker.is_user).length === 1
              && voiceEnrolled === false && (
              <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 font-body text-xs text-amber-800">
                Mic-only calls identify you more reliably after voice calibration.{" "}
                <button
                  type="button"
                  onClick={onOpenVoiceSettings}
                  className="font-semibold underline"
                >
                  Open Transcription &amp; Audio
                </button>
              </p>
            )}
            <button
              onClick={onStartCall}
              disabled={isStarting}
              className="w-full py-3 rounded-lg font-display font-semibold text-white text-lg
                         bg-brand-teal hover:bg-brand-teal-dark transition-colors
                         shadow-md hover:shadow-lg focus:ring-2
                         focus:ring-brand-teal-light focus:ring-offset-2
                         disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isStarting ? "Starting..." : "Start Call"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
