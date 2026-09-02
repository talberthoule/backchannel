import { useEffect, useState } from "react";
import type { CallSegment, Directive, Document, ModelPricingResponse, PostProcessingProgress, Question, Session, SessionSynthesis, Speaker, TokenUsageSummary, TranscriptEntry } from "../../types";
import TranscriptReview from "./TranscriptReview";
import CallAudioPanel from "./CallAudioPanel";
import MeetingChat from "./MeetingChat";
import QuestionSummary from "./QuestionSummary";
import BriefingView from "./BriefingView";
import OverviewView, { type OverviewTarget } from "./OverviewView";
import PostCallTabs, { panelId, tabId, type PostCallTabDef } from "./PostCallTabs";
import ExportMenu from "./ExportMenu";
import TokenUsagePanel from "./TokenUsagePanel";
import SpeakerNameMapper from "../SpeakerNameMapper";
import EditableSessionName from "../EditableSessionName";
import * as api from "../../services/api";
import { formatPostProcessingSummary, parseSavedDrainSummary } from "../../lib/postProcessingSummary";

interface PostCallViewProps {
  session: Session;
  questions: Question[];
  transcripts: TranscriptEntry[];
  directives: Directive[];
  documents: Document[];
  segments: CallSegment[];
  speakers: Speaker[];
  synthesis: SessionSynthesis | null;
  signalHistoryCount: number;
  onResumeCall: () => void;
  onDeleteSession: () => void;
  onRefreshSpeakers: () => void;
  onRefreshSession: () => void;
  onRefreshQuestions: () => void;
  onRefreshSynthesis: () => Promise<unknown>;
  onOpenAdminAgents: () => void;
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

// Overview is the landing worksheet: the executive read over everything the
// session captured. Insights stays the raw record behind it.
type Tab = "overview" | "briefing" | "insights" | "transcript" | "chat" | "speakers" | "directives" | "documents" | "tokens";

export default function PostCallView({
  session,
  questions,
  transcripts,
  directives,
  documents,
  segments,
  speakers,
  synthesis,
  signalHistoryCount,
  onResumeCall,
  onDeleteSession,
  onRefreshSpeakers,
  onRefreshSession,
  onRefreshQuestions,
  onRefreshSynthesis,
  onOpenAdminAgents,
  onRenameSession,
  onRetranscribed,
  postProcessing,
}: PostCallViewProps) {
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  // The Insights group an Overview tile deep-links into. QuestionSummary reads
  // it at mount (it mounts on every tab switch), and it resets to "all" when
  // the reader leaves Insights or clicks the tab directly, so a deep link
  // never lingers as a hidden filter.
  const [insightsFilter, setInsightsFilter] = useState("all");
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [refreshingBriefing, setRefreshingBriefing] = useState(false);
  const [tokenUsage, setTokenUsage] = useState<TokenUsageSummary | null>(null);
  // Overview is the landing tab, so the usage request starts at mount: begin
  // in the loading state rather than flashing "unavailable" for one frame.
  const [tokenUsageLoading, setTokenUsageLoading] = useState(true);
  const [tokenUsageError, setTokenUsageError] = useState(false);
  const [tokenUsageRequest, setTokenUsageRequest] = useState(0);
  const [modelPricing, setModelPricing] = useState<ModelPricingResponse | null>(null);
  const [briefingError, setBriefingError] = useState<string | null>(null);
  const speakerActionsLocked = Boolean(postProcessing?.active || postProcessing?.state === "timeout" || postProcessing?.state === "error");
  const progressSummary = formatPostProcessingSummary(postProcessing?.details);
  // The live banner only exists for a client that was still connected when the
  // drain finished. A disconnect mid-drain used to lose the record entirely, so
  // fall back to what the backend saved on the session (ALP-103).
  const savedDrain = parseSavedDrainSummary(session.drain_summary);
  const savedDrainSummary = savedDrain ? formatPostProcessingSummary(savedDrain) : null;
  const showSavedDrain = Boolean(savedDrain) && !(postProcessing?.state === "completed" && postProcessing.confirmed);

  // Overview's cost tile and the Tokens tab share one fetch. Keying the effect
  // on the boolean rather than the tab means moving between the two does not
  // re-request; leaving for another tab and coming back does.
  const wantsUsage = activeTab === "overview" || activeTab === "tokens";

  // How many values the PII Shield holds for this session. Counts only: the
  // request decrypts nothing, so it is not a reveal.
  const [shieldedCount, setShieldedCount] = useState(0);
  useEffect(() => {
    let cancelled = false;
    api.getSessionPiiSummary(session.id)
      .then((summary) => { if (!cancelled) setShieldedCount(summary.total); })
      .catch(() => { if (!cancelled) setShieldedCount(0); });
    return () => { cancelled = true; };
  }, [session.id]);

  useEffect(() => {
    if (!wantsUsage) return;
    let cancelled = false;
    setTokenUsageLoading(true);
    setTokenUsageError(false);
    api.getTokenUsage(session.id)
      .then((usage) => {
        if (!cancelled) setTokenUsage(usage);
      })
      .catch(() => {
        if (!cancelled) setTokenUsageError(true);
      })
      .finally(() => {
        if (!cancelled) setTokenUsageLoading(false);
      });
    return () => { cancelled = true; };
  }, [wantsUsage, postProcessing?.state, session.id, tokenUsageRequest]);

  // Pricing powers the Est. cost column; best-effort so a failed fetch just
  // hides the column instead of breaking the token tables.
  useEffect(() => {
    if (!wantsUsage || modelPricing) return;
    let cancelled = false;
    api.getModelPricing()
      .then((response) => {
        if (!cancelled) setModelPricing(response);
      })
      .catch(() => { /* leave modelPricing null; tables render without costs */ });
    return () => { cancelled = true; };
  }, [wantsUsage, modelPricing]);

  useEffect(() => {
    if (activeTab !== "insights") setInsightsFilter("all");
  }, [activeTab]);

  const selectTab = (tab: Tab) => {
    if (tab === "insights") setInsightsFilter("all");
    setActiveTab(tab);
  };

  const navigateFromOverview = (target: OverviewTarget) => {
    if (target.tab === "insights") setInsightsFilter(target.filter ?? "all");
    setActiveTab(target.tab);
  };

  // Post-call analysis for a session that only has a transcript (an import
  // that was never processed, or a call whose agents were all off). Runs the
  // same endpoint the pre-call import flow uses, then pulls the briefing.
  const handleAnalyze = async () => {
    setAnalyzing(true);
    setAnalyzeError(null);
    try {
      await api.analyzeSession(session.id);
      try {
        await api.refreshSynthesis(session.id);
      } catch (err) {
        setAnalyzeError(err instanceof Error ? `Analysis finished, but the briefing failed: ${err.message}` : "Analysis finished, but the briefing failed.");
      }
    } catch (err) {
      setAnalyzeError(err instanceof Error ? err.message : "Transcript analysis failed.");
    } finally {
      await Promise.allSettled([onRefreshQuestions(), onRefreshSession(), onRefreshSynthesis()]);
      setAnalyzing(false);
    }
  };

  const handleRenameSpeaker = async (speakerId: string, newName: string) => {
    await api.updateSpeaker(session.id, speakerId, { name: newName });
    onRefreshSpeakers();
    onRefreshSession();
  };

  const userDocuments = documents;

  const tabs: PostCallTabDef<Tab>[] = [
    { key: "overview", label: "Overview" },
    { key: "briefing", label: "Briefing" },
    { key: "insights", label: "Insights", count: questions.length },
    { key: "transcript", label: "Transcript" },
    { key: "chat", label: "Chat" },
    { key: "speakers", label: "Speakers", count: speakers.length },
    { key: "documents", label: "Documents", count: documents.length },
    { key: "directives", label: "Directives", count: directives.length },
    { key: "tokens", label: "Tokens" },
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
      {/* Completion notes take the accent tint through the semantic tokens,
          like the amber notice below, so they sit quietly on both themes. */}
      {postProcessing?.state === "completed" && postProcessing.confirmed && (
        <div role="status" className="rounded-lg border border-brand-teal/30 bg-brand-teal/10 px-4 py-3">
          <p className="font-body text-sm font-semibold text-brand-dark-gray">
            {postProcessing.message || "Post-processing complete"}
          </p>
          {progressSummary && (
            <p className="mt-1 font-body text-xs text-brand-gray">{progressSummary}</p>
          )}
        </div>
      )}

      {showSavedDrain && savedDrain && (
        <div role="status" className="rounded-lg border border-brand-teal/30 bg-brand-teal/10 px-4 py-3">
          <p className="font-body text-sm font-semibold text-brand-dark-gray">
            {savedDrain.message || "Post-processing complete"}
          </p>
          {savedDrainSummary && (
            <p className="mt-1 font-body text-xs text-brand-gray">{savedDrainSummary}</p>
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
                    {/* A resume is ordinary, not a warning: neutral rather than amber. */}
                    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      seg.segment_number === 1
                        ? "bg-brand-teal/10 text-brand-teal"
                        : "bg-brand-light-gray-2 text-brand-gray"
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
            {shieldedCount > 0 && (
              <span
                className="inline-flex items-center gap-1.5 rounded-full border border-brand-teal/30 bg-brand-teal/10 px-2.5 py-1 font-body text-xs font-medium text-brand-teal"
                title="Names, contact details and identifiers in this session are stored as tokens; the real values are shown only here."
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 3l7 3v5c0 5-3.5 8.5-7 10-3.5-1.5-7-5-7-10V6l7-3z" />
                </svg>
                {shieldedCount} shielded
              </span>
            )}
            <ExportMenu sessionId={session.id} shielded={shieldedCount > 0} />
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
      <PostCallTabs tabs={tabs} activeTab={activeTab} onSelect={selectTab} />

      {/* Tab content: one panel, named by whichever tab is selected. */}
      <div role="tabpanel" id={panelId(activeTab)} aria-labelledby={tabId(activeTab)}>
      {activeTab === "overview" && (
        <OverviewView
          session={session}
          questions={questions}
          transcripts={transcripts}
          speakers={speakers}
          segments={segments}
          synthesis={synthesis}
          tokenUsage={tokenUsage}
          tokenUsageLoading={tokenUsageLoading}
          tokenUsageError={tokenUsageError}
          modelPricing={modelPricing}
          onNavigate={navigateFromOverview}
          onAnalyze={transcripts.length > 0 && questions.length === 0 ? handleAnalyze : undefined}
          analyzing={analyzing}
          analyzeError={analyzeError}
        />
      )}
      {activeTab === "briefing" && (
        <BriefingView
          session={session}
          synthesis={synthesis}
          signalHistoryCount={signalHistoryCount}
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
          initialFilter={insightsFilter}
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
          key={session.id}
          session={session}
          speakers={speakers}
          onRefresh={onRefreshSpeakers}
          onRefreshSession={onRefreshSession}
          onRefreshQuestions={onRefreshQuestions}
          onRefreshSynthesis={onRefreshSynthesis}
          onOpenAdminAgents={onOpenAdminAgents}
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
                      <span className="text-2xl" aria-hidden="true">{fileIcon(doc.mime_type)}</span>
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

      {activeTab === "tokens" && (
        <TokenUsagePanel
          tokenUsage={tokenUsage}
          loading={tokenUsageLoading}
          error={tokenUsageError}
          pricing={modelPricing}
          onRefresh={() => setTokenUsageRequest((value) => value + 1)}
        />
      )}
      </div>
    </div>
  );
}
