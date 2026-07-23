import { useState } from "react";
import type { CallSegment, Directive, Document, PostProcessingProgress, Question, Session, SessionSynthesis, Speaker, TranscriptEntry } from "../../types";
import TranscriptReview from "./TranscriptReview";
import CallAudioPanel from "./CallAudioPanel";
import MeetingChat from "./MeetingChat";
import QuestionSummary from "./QuestionSummary";
import BriefingView from "./BriefingView";
import SpeakerNameMapper from "../SpeakerNameMapper";
import EditableSessionName from "../EditableSessionName";
import * as api from "../../services/api";

interface PostCallViewProps {
  session: Session;
  questions: Question[];
  transcripts: TranscriptEntry[];
  directives: Directive[];
  documents: Document[];
  segments: CallSegment[];
  speakers: Speaker[];
  synthesis: SessionSynthesis | null;
  onResumeCall: () => void;
  onDeleteSession: () => void;
  onRefreshSpeakers: () => void;
  onRefreshSession: () => void;
  onRefreshQuestions: () => void;
  onRefreshSynthesis: () => Promise<unknown>;
  onRenameSession: (name: string) => Promise<void>;
  onRetranscribed?: () => Promise<void> | void;
  postProcessing?: PostProcessingProgress;
}

function formatDuration(startedAt: string | null, endedAt: string | null): string {
  if (!startedAt || !endedAt) return "In progress";
  const ms = new Date(endedAt).getTime() - new Date(startedAt).getTime();
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function formatTime(iso: string | null): string {
  if (!iso) return "N/A";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDate(iso: string | null): string {
  if (!iso) return "N/A";
  return new Date(iso).toLocaleDateString();
}

function fileIcon(mimeType: string): string {
  if (mimeType.startsWith("image/")) return "🖼";
  if (mimeType.includes("pdf")) return "📄";
  if (mimeType.includes("spreadsheet") || mimeType.includes("excel") || mimeType.includes("csv")) return "📊";
  if (mimeType.includes("presentation") || mimeType.includes("powerpoint")) return "📑";
  if (mimeType.includes("word") || mimeType.includes("document")) return "📝";
  if (mimeType.startsWith("text/")) return "📃";
  return "📎";
}

function formatFileSize(mimeType: string): string {
  const parts = mimeType.split("/");
  return parts[parts.length - 1].replace("vnd.openxmlformats-officedocument.", "").replace("spreadsheetml.sheet", "xlsx").replace("presentationml.presentation", "pptx").replace("wordprocessingml.document", "docx").toUpperCase();
}

function postProcessingSummary(progress?: PostProcessingProgress): string | null {
  if (!progress?.details) return null;
  const insights = Number(progress.details.insights_saved ?? 0);
  const synthOps = Number(progress.details.synthesizer_ops ?? 0);
  const opportunityOps = Number(progress.details.opportunity_ops ?? 0);
  const parts = [
    insights ? `${insights} insight${insights === 1 ? "" : "s"} saved` : null,
    synthOps ? `${synthOps} insight update${synthOps === 1 ? "" : "s"}` : null,
    opportunityOps ? `${opportunityOps} offering match${opportunityOps === 1 ? "" : "es"}` : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" | ") : null;
}

type Tab = "briefing" | "insights" | "transcript" | "chat" | "speakers" | "directives" | "documents";

export default function PostCallView({
  session,
  questions,
  transcripts,
  directives,
  documents,
  segments,
  speakers,
  synthesis,
  onResumeCall,
  onDeleteSession,
  onRefreshSpeakers,
  onRefreshSession,
  onRefreshQuestions,
  onRefreshSynthesis,
  onRenameSession,
  onRetranscribed,
  postProcessing,
}: PostCallViewProps) {
  const [activeTab, setActiveTab] = useState<Tab>("briefing");
  const [refreshingBriefing, setRefreshingBriefing] = useState(false);
  const [briefingError, setBriefingError] = useState<string | null>(null);
  const speakerActionsLocked = Boolean(postProcessing?.active || postProcessing?.state === "timeout" || postProcessing?.state === "error");
  const progressSummary = postProcessingSummary(postProcessing);

  const handleRenameSpeaker = async (speakerId: string, newName: string) => {
    await api.updateSpeaker(session.id, speakerId, { name: newName });
    onRefreshSpeakers();
    onRefreshSession();
  };

  const userDocuments = documents;

  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: "briefing", label: "Briefing" },
    { key: "insights", label: "Insights", count: questions.length },
    { key: "transcript", label: "Transcript" },
    { key: "chat", label: "Chat" },
    { key: "speakers", label: "Speakers", count: speakers.length },
    { key: "documents", label: "Documents", count: documents.length },
    { key: "directives", label: "Directives", count: directives.length },
  ];

  // Calculate total duration across all segments
  const totalDurationMs = segments.reduce((sum, seg) => {
    if (seg.started_at && seg.ended_at) {
      return sum + (new Date(seg.ended_at).getTime() - new Date(seg.started_at).getTime());
    }
    return sum;
  }, 0);
  const totalSeconds = Math.floor(totalDurationMs / 1000);
  const totalHours = Math.floor(totalSeconds / 3600);
  const totalMinutes = Math.floor((totalSeconds % 3600) / 60);
  const totalSecs = totalSeconds % 60;
  const totalDurationStr = totalHours > 0
    ? `${totalHours}h ${totalMinutes}m ${totalSecs}s`
    : totalMinutes > 0
      ? `${totalMinutes}m ${totalSecs}s`
      : `${totalSecs}s`;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      {postProcessing?.state === "completed" && postProcessing.confirmed && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3">
          <p className="font-body text-sm font-semibold text-green-800">
            {postProcessing.message || "Post-processing complete"}
          </p>
          {progressSummary && (
            <p className="mt-1 font-body text-xs text-green-700">{progressSummary}</p>
          )}
        </div>
      )}

      {speakerActionsLocked && (
        <div className="rounded-lg border border-brand-amber/30 bg-brand-amber/10 px-4 py-3">
          <p className="font-body text-sm font-semibold text-brand-dark-gray">
            Post-processing is not confirmed complete.
          </p>
          <p className="mt-1 font-body text-xs text-brand-gray">
            Speaker mapping, speaker renames, merges, and insight enhancement are paused until completion is confirmed.
          </p>
        </div>
      )}

      {/* Session summary header */}
      <div className="rounded-xl bg-surface p-6 shadow-sm">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <EditableSessionName
              name={session.name}
              onRename={onRenameSession}
              className="text-brand-dark-gray"
            />

            {/* Call segments timeline */}
            <div className="mt-4 space-y-2">
              {segments.length > 0 ? (
                segments.map((seg) => (
                  <div
                    key={seg.id}
                    className="flex items-center gap-4 text-sm"
                  >
                    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      seg.segment_number === 1
                        ? "bg-brand-teal/10 text-brand-teal"
                        : "bg-brand-amber/10 text-brand-amber"
                    }`}>
                      {seg.segment_number === 1 ? "Call" : `Resume ${seg.segment_number - 1}`}
                    </span>
                    <span className="text-brand-gray">
                      {formatTime(seg.started_at)} — {formatTime(seg.ended_at)}
                    </span>
                    <span className="text-brand-mid-gray">
                      {formatDuration(seg.started_at, seg.ended_at)}
                    </span>
                  </div>
                ))
              ) : (
                // Fallback to session-level times if no segments exist
                <div className="flex flex-wrap gap-6 text-sm text-brand-gray">
                  <div>
                    <span className="font-medium text-brand-mid-gray">Started:</span>{" "}
                    {formatTime(session.started_at)}
                  </div>
                  <div>
                    <span className="font-medium text-brand-mid-gray">Ended:</span>{" "}
                    {formatTime(session.ended_at)}
                  </div>
                  <div>
                    <span className="font-medium text-brand-mid-gray">Duration:</span>{" "}
                    {formatDuration(session.started_at, session.ended_at)}
                  </div>
                </div>
              )}
            </div>

            {/* Summary stats row */}
            <div className="mt-3 flex gap-6 text-sm text-brand-gray">
              <div>
                <span className="font-medium text-brand-mid-gray">Date:</span>{" "}
                {formatDate(session.started_at)}
              </div>
              {segments.length > 1 && (
                <div>
                  <span className="font-medium text-brand-mid-gray">Total Time:</span>{" "}
                  {totalDurationStr} across {segments.length} calls
                </div>
              )}
              <div>
                <span className="font-medium text-brand-mid-gray">Insights:</span>{" "}
                {questions.length}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={onResumeCall}
              className="rounded-lg bg-brand-teal px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-teal-dark shadow-sm"
            >
              Resume Call
            </button>
            <div className="relative group">
              <button className="rounded-lg border border-brand-light-gray-1 px-4 py-2 text-sm font-medium text-brand-teal transition-colors hover:bg-brand-light-gray-2">
                Export
              </button>
              <div className="absolute right-0 top-full mt-1 w-48 rounded-lg border border-brand-light-gray-1 bg-surface shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-10">
                <a
                  href={`/api/sessions/${session.id}/artifacts/summary-export`}
                  className="block px-4 py-2.5 text-sm text-brand-dark-gray hover:bg-brand-light-gray-2 rounded-t-lg"
                >
                  Full Summary (HTML)
                </a>
                <a
                  href={`/api/sessions/${session.id}/artifacts/questions-export`}
                  className="block px-4 py-2.5 text-sm text-brand-dark-gray hover:bg-brand-light-gray-2"
                >
                  Insights (Excel)
                </a>
                {session.speaker_context_enhanced_at && (
                  <a
                    href={`/api/sessions/${session.id}/artifacts/questions-export?enhanced_only=true`}
                    className="block px-4 py-2.5 text-sm text-brand-dark-gray hover:bg-brand-light-gray-2"
                  >
                    Enhanced Insights (Excel)
                  </a>
                )}
                <a
                  href={`/api/sessions/${session.id}/artifacts/transcript-export`}
                  className="block px-4 py-2.5 text-sm text-brand-dark-gray hover:bg-brand-light-gray-2 rounded-b-lg"
                >
                  Transcript (TXT)
                </a>
              </div>
            </div>
            <button
              onClick={onDeleteSession}
              className="rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 hover:border-red-300"
            >
              Delete Session
            </button>
          </div>
        </div>
      </div>

      {/* Tab navigation */}
      <div className="flex gap-1 rounded-lg bg-brand-light-gray-2 p-1">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex-1 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.key
                ? "bg-surface text-brand-teal shadow-sm"
                : "text-brand-gray hover:text-brand-dark-gray"
            }`}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="ml-1.5 text-xs text-brand-mid-gray">({tab.count})</span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "briefing" && (
        <BriefingView
          session={session}
          synthesis={synthesis}
          refreshing={refreshingBriefing}
          error={briefingError}
          onRefresh={async () => {
            setRefreshingBriefing(true);
            setBriefingError(null);
            try {
              await api.refreshSynthesis(session.id);
              await onRefreshSynthesis();
            } catch (err) {
              setBriefingError(
                err instanceof Error ? err.message : "Briefing generation failed."
              );
            } finally {
              setRefreshingBriefing(false);
            }
          }}
        />
      )}
      {activeTab === "insights" && (
        <QuestionSummary
          questions={questions}
          speakers={speakers}
          showEnhanced={Boolean(session.speaker_context_enhanced_at)}
        />
      )}
      {activeTab === "chat" && <MeetingChat key={session.id} session={session} />}
      {activeTab === "transcript" && (
        <>
          <CallAudioPanel session={session} segments={segments} onRetranscribed={() => onRetranscribed?.()} />
          <TranscriptReview transcripts={transcripts} speakers={speakers} onRenameSpeaker={speakerActionsLocked ? undefined : handleRenameSpeaker} />
        </>
      )}

      {activeTab === "speakers" && (
        <SpeakerNameMapper
          session={session}
          speakers={speakers}
          onRefresh={onRefreshSpeakers}
          onRefreshSession={onRefreshSession}
          onRefreshQuestions={onRefreshQuestions}
          onRefreshSynthesis={onRefreshSynthesis}
          disabled={speakerActionsLocked}
          disabledReason="Post-processing must complete before speaker mappings or insight enhancement can be changed."
        />
      )}

      {activeTab === "documents" && (
        <div className="rounded-xl bg-surface p-6 shadow-sm">
          <h2 className="font-display text-lg font-semibold text-brand-dark-gray mb-4">
            Shared Files
          </h2>
          {documents.length === 0 ? (
            <p className="text-brand-mid-gray text-sm">No files were shared for this call.</p>
          ) : (
            <div className="space-y-6">
              <div>
                <h3 className="text-sm font-semibold text-brand-gray uppercase tracking-wide mb-3">
                  Uploaded by User (Pre-Call)
                </h3>
                <div className="space-y-2">
                  {userDocuments.map((doc) => (
                    <div
                      key={doc.id}
                      className="flex items-center gap-4 rounded-lg border border-brand-light-gray-1 p-4 hover:bg-brand-light-gray-2/50 transition-colors"
                    >
                      <span className="text-2xl">{fileIcon(doc.mime_type)}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-brand-dark-gray truncate">
                          {doc.filename}
                        </p>
                        <p className="text-xs text-brand-mid-gray mt-0.5">
                          {formatFileSize(doc.mime_type)} &middot; Uploaded {new Date(doc.uploaded_at).toLocaleString()}
                        </p>
                      </div>
                      {doc.gemini_file_uri && (
                        <span className="shrink-0 rounded-full bg-green-50 px-2.5 py-0.5 text-xs font-medium text-green-700">
                          Indexed by AI
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <h3 className="text-sm font-semibold text-brand-gray uppercase tracking-wide mb-3">
                  Generated by AI Assistant
                </h3>
                <p className="text-brand-mid-gray text-sm italic">
                  No AI-generated artifacts for this session.
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === "directives" && (
        <div className="rounded-xl bg-surface p-6 shadow-sm">
          <h2 className="font-display text-lg font-semibold text-brand-dark-gray mb-4">
            Framing Context & Directives
          </h2>
          {directives.length === 0 ? (
            <p className="text-brand-mid-gray text-sm">No directives were set for this call.</p>
          ) : (
            <div className="space-y-3">
              {directives.map((d) => (
                <div
                  key={d.id}
                  className={`rounded-lg border p-4 ${
                    d.active
                      ? "border-brand-teal-light/30 bg-brand-teal/5"
                      : "border-brand-light-gray-1 bg-brand-light-gray-2 opacity-60"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm text-brand-dark-gray leading-relaxed">{d.text}</p>
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
                        d.active
                          ? "bg-brand-teal/10 text-brand-teal"
                          : "bg-brand-light-gray-1 text-brand-mid-gray"
                      }`}
                    >
                      {d.active ? "Active" : "Inactive"}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-brand-mid-gray">
                    Added {new Date(d.created_at).toLocaleString()}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
