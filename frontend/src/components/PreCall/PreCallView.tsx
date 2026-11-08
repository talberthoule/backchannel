import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { Directive, Document, Session, Speaker } from "../../types";
import * as api from "../../services/api";
import DocumentUpload from "./DocumentUpload";
import DirectiveInput from "./DirectiveInput";
import DirectiveList from "./DirectiveList";
import AgentSelector from "./AgentSelector";
import MeetingContextSetup, { meetingTypeCopy } from "./MeetingContextSetup";
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
  const { t } = useTranslation();
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
              {optional && <span className="ml-1.5 font-body text-[11px] font-normal text-brand-mid-gray">{t("preCall.optional")}</span>}
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
  const { t } = useTranslation();
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

  const typeLabel = meetingTypeCopy(session.meeting_type, t).label;
  const activeDirectives = directives.filter((d) => d.active).length;
  const readiness = [
    typeLabel,
    documents.length ? t("preCall.count.documents", { count: documents.length }) : null,
    activeDirectives ? t("preCall.count.directives", { count: activeDirectives }) : null,
    speakers.length ? t("preCall.count.participants", { count: speakers.length }) : t("preCall.autoDetectedParticipants"),
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
              {processingTranscript ? t("preCall.processing") : t("preCall.processTranscript")}
            </button>
          ) : (
            <button
              type="button"
              onClick={onStartCall}
              disabled={isStarting}
              className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-brand-teal px-5 py-2.5 font-display text-sm font-semibold text-white shadow-md transition-colors hover:bg-brand-teal-dark hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-brand-teal-light focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className={`inline-block h-2 w-2 rounded-full ${isStarting ? "animate-pulse bg-white/70" : "bg-white"}`} aria-hidden="true" />
              {isStarting ? t("preCall.starting") : t("preCall.startCall")}
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
                <span className="font-display text-sm font-semibold text-brand-dark-gray">{t("preCall.captureMeetingAudio")}</span>
                <span className="mt-0.5 block font-body text-xs leading-relaxed text-brand-mid-gray">
                  {t("preCall.captureMeetingAudioBody")}
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
                {t("preCall.micOnlyWarning")}
                {soleUserNeedsVoice && (
                  <>
                    {" "}{t("preCall.voiceCalibrationHint")}{" "}
                    <button type="button" onClick={onOpenVoiceSettings} className="font-semibold underline">
                      {t("preCall.openTranscriptionAudio")}
                    </button>
                  </>
                )}
              </p>
            )}
            <p className="mt-3 flex flex-wrap items-center gap-x-2 font-body text-xs text-brand-gray">
              <span className="text-brand-amber" aria-hidden="true">&#9888;</span>
              <span>{t("preCall.recordingNotice")}</span>
              <button
                type="button"
                onClick={() => setShowConsent((v) => !v)}
                aria-expanded={showConsent}
                className="font-semibold text-brand-teal hover:underline"
              >
                {showConsent ? t("preCall.less") : t("preCall.more")}
              </button>
            </p>
            {showConsent && (
              <p className="mt-2 font-body text-xs leading-relaxed text-brand-mid-gray">
                {t("preCall.consentDetails")}
              </p>
            )}
          </div>
        )}

        <SetupSection
          title={t("preCall.sections.context")}
          summary={session.meeting_context ? session.meeting_context : t("preCall.sections.contextSummary")}
          defaultOpen
          tooltip={{
            content: t("preCall.sections.contextTooltip"),
            details: [
              t("preCall.sections.contextInternal"),
              t("preCall.sections.contextVendor"),
              t("preCall.sections.contextClient"),
            ],
          }}
        >
          <MeetingContextSetup session={session} onUpdate={onUpdateSessionContext} />
        </SetupSection>

        <SetupSection
          title={t("preCall.sections.documents")}
          optional
          summary={documents.length ? documents.map((d) => d.filename).join(", ") : t("preCall.sections.documentsSummary")}
          defaultOpen={documents.length > 0}
          tooltip={{
            content: t("preCall.sections.documentsTooltip"),
            details: [
              t("preCall.sections.documentsGemini"),
              t("preCall.sections.documentsPrivacy"),
              t("preCall.sections.documentsTypes"),
              t("preCall.sections.documentsPersist"),
            ],
          }}
        >
          <DocumentUpload sessionId={session.id} documents={documents} onRefresh={onRefreshDocuments} />
        </SetupSection>

        <SetupSection
          title={t("preCall.sections.import")}
          optional
          summary={hasImportedTranscript ? t("preCall.count.lines", { count: transcriptCount }) : t("preCall.sections.importSummary")}
          defaultOpen={hasImportedTranscript}
          tooltip={{
            content: t("preCall.sections.importTooltip"),
            details: [
              t("preCall.sections.importTranscriptTypes"),
              t("preCall.sections.importAudioTypes"),
              t("preCall.sections.importAction"),
            ],
          }}
        >
          <TranscriptImport sessionId={session.id} onImported={handleImported} />
        </SetupSection>

        <SetupSection
          title={t("preCall.sections.directives")}
          optional
          summary={activeDirectives ? t("preCall.count.activeDirective", { count: activeDirectives }) : t("preCall.sections.directivesSummary")}
          defaultOpen={directives.length > 0}
          tooltip={{
            content: t("preCall.sections.directivesTooltip"),
            details: [
              t("preCall.sections.directivesExample"),
              t("preCall.sections.directivesToggle"),
              t("preCall.sections.directivesActive"),
              t("preCall.sections.directivesMidCall"),
            ],
          }}
        >
          <div className="space-y-4">
            <DirectiveInput sessionId={session.id} onAdded={onRefreshDirectives} />
            <DirectiveList sessionId={session.id} directives={directives} onRefresh={onRefreshDirectives} />
          </div>
        </SetupSection>

        <SetupSection
          title={t("preCall.sections.participants")}
          optional
          summary={speakers.length ? speakers.map((s) => s.name).join(", ") : t("preCall.sections.participantsSummary")}
          defaultOpen={speakers.length > 0}
          tooltip={{
            content: t("preCall.sections.participantsTooltip"),
            details: [
              t("preCall.sections.participantsNames"),
              t("preCall.sections.participantsMe"),
              t("preCall.sections.participantsAccuracy"),
              t("preCall.sections.participantsRename"),
            ],
          }}
        >
          <SpeakerSetup sessionId={session.id} speakers={speakers} onRefresh={onRefreshSpeakers} />
        </SetupSection>

        <SetupSection
          title={t("preCall.sections.agents")}
          optional
          summary={t("preCall.sections.agentsSummary")}
          defaultOpen={false}
          tooltip={{
            content: t("preCall.sections.agentsTooltip"),
            details: [
              t("preCall.sections.agentsAnalyst"),
              t("preCall.sections.agentsPrincipal"),
              t("preCall.sections.agentsOpportunity"),
              t("preCall.sections.agentsAudio"),
              t("preCall.sections.agentsOverride"),
            ],
          }}
        >
          <AgentSelector sessionId={session.id} />
        </SetupSection>
      </div>
    </div>
  );
}
