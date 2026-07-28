import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentActivitySnapshot, AudioSendStats, MeetingType, PostProcessingProgress as PostProcessingProgressState, Question, Session, SessionSynthesis, Speaker, StopDrainMode, TranscriptEntry } from "../../types";
import AgentActivityPanel, { activityEmptyMessage } from "./AgentActivityPanel";
import AudioIndicator from "./AudioIndicator";
import DirectiveBar from "./DirectiveBar";
import PostProcessingProgress from "./PostProcessingProgress";
import QuestionList from "./QuestionList";
import SynthesisSignals, { getLiveSignalInsightIds } from "./SynthesisSignals";
import TranscriptPanel from "./TranscriptPanel";

interface ActiveCallViewProps {
  session: Session;
  questions: Question[];
  transcripts: TranscriptEntry[];
  onEndCall: (drain?: StopDrainMode) => void;
  onResumeAudio: () => void;
  onStarQuestion: (id: string, starred: boolean) => void;
  onDismissQuestion: (id: string) => void;
  onVoteQuestion: (id: string, vote: number) => void | Promise<void>;
  onAddDirective: (text: string) => void;
  onUpdateSessionContext: (data: { meeting_type?: MeetingType; meeting_context?: string }) => Promise<void>;
  audioLevel: number;
  systemAudioLevel?: number;
  systemAudioActive?: boolean;
  isCapturing: boolean;
  isStarting: boolean;
  audioStats: AudioSendStats;
  backendAudioStatus: string | null;
  captureError: string | null;
  status: string;
  callSegmentStart: string | null;
  speakers: Speaker[];
  postProcessing?: PostProcessingProgressState;
  synthesis: SessionSynthesis | null;
  activity: AgentActivitySnapshot | null;
}

const MEETING_TYPE_OPTIONS: { value: MeetingType; label: string }[] = [
  { value: "general", label: "General" },
  { value: "client_sales", label: "Client / prospect" },
  { value: "customer_delivery", label: "Customer delivery" },
  { value: "internal_enablement", label: "Internal enablement" },
  { value: "internal_checkin", label: "Internal check-in" },
  { value: "vendor_partner", label: "Vendor / partner" },
];

function useSessionTimer(startedAt: string | null) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startedAt) {
      setElapsed(0);
      return;
    }
    const start = new Date(startedAt).getTime();
    if (!Number.isFinite(start)) {
      setElapsed(0);
      return;
    }

    function tick() {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }

    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [startedAt]);

  const hours = Math.floor(elapsed / 3600);
  const minutes = Math.floor((elapsed % 3600) / 60);
  const seconds = elapsed % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export default function ActiveCallView({
  session,
  questions,
  transcripts,
  onEndCall,
  onResumeAudio,
  onStarQuestion,
  onDismissQuestion,
  onVoteQuestion,
  onAddDirective,
  onUpdateSessionContext,
  audioLevel,
  systemAudioLevel,
  systemAudioActive,
  isCapturing,
  isStarting,
  audioStats,
  backendAudioStatus,
  captureError,
  status,
  callSegmentStart,
  speakers,
  postProcessing,
  synthesis,
  activity,
}: ActiveCallViewProps) {
  const [debugOpen, setDebugOpen] = useState(false);
  const [contextExpanded, setContextExpanded] = useState(false);
  const [endMenuOpen, setEndMenuOpen] = useState(false);
  const endMenuRef = useRef<HTMLDivElement | null>(null);
  const autoUpvotedSignalIds = useRef<Set<string>>(new Set());
  const timerDisplay = useSessionTimer(callSegmentStart);
  const postProcessingActive = postProcessing?.active ?? false;
  const backendDisconnected = status !== "connected";
  const audioSeconds = Math.round(audioStats.bytesSent / 32000);
  const lastAudioAge =
    audioStats.lastSentAt
      ? Math.max(0, Math.round((Date.now() - new Date(audioStats.lastSentAt).getTime()) / 1000))
      : null;
  const captureStatus = isStarting
    ? "Starting audio..."
    : isCapturing && status === "connected"
      ? "Listening"
      : status;

  // Normalize questions: WS-sourced questions may lack starred/dismissed/created_at
  const normalizedQuestions = useMemo(
    () =>
      questions.map((q) => ({
        ...q,
        starred: q.starred ?? false,
        dismissed: q.dismissed ?? false,
        created_at: q.created_at ?? new Date().toISOString(),
      })),
    [questions]
  );

  const strategicSignalQuestionIds = useMemo(() => {
    const knownQuestionIds = new Set(normalizedQuestions.map((q) => q.id));
    return [...getLiveSignalInsightIds(synthesis)].filter((id) => knownQuestionIds.has(id));
  }, [normalizedQuestions, synthesis]);

  const strategicSignalQuestionIdSet = useMemo(
    () => new Set(strategicSignalQuestionIds),
    [strategicSignalQuestionIds]
  );

  useEffect(() => {
    for (const id of strategicSignalQuestionIds) {
      const question = normalizedQuestions.find((q) => q.id === id);
      if (!question || (question.vote ?? 0) > 0 || autoUpvotedSignalIds.current.has(id)) continue;

      autoUpvotedSignalIds.current.add(id);
      Promise.resolve(onVoteQuestion(id, 1)).catch((err) => {
        autoUpvotedSignalIds.current.delete(id);
        console.error("Failed to upvote live strategic signal insight", err);
      });
    }
  }, [normalizedQuestions, onVoteQuestion, strategicSignalQuestionIds]);

  useEffect(() => {
    if (!endMenuOpen) return;
    function handlePointerDown(event: MouseEvent) {
      if (endMenuRef.current && !endMenuRef.current.contains(event.target as Node)) {
        setEndMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [endMenuOpen]);

  const displayQuestions = useMemo(
    () =>
      normalizedQuestions.map((q) =>
        strategicSignalQuestionIdSet.has(q.id) && (q.vote ?? 0) <= 0
          ? { ...q, vote: 1 }
          : q
      ),
    [normalizedQuestions, strategicSignalQuestionIdSet]
  );
  const emptyInsightMessage = activityEmptyMessage(
    activity,
    displayQuestions.length > 0,
  );

  return (
    <div className="flex h-full flex-col bg-canvas">
      {/* Top bar */}
      <header className="flex items-center justify-between gap-4 border-b border-brand-light-gray-1 bg-surface px-4 py-3 md:px-6">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
          <AudioIndicator isCapturing={isCapturing} audioLevel={audioLevel} />
          {systemAudioActive && (
            <span className="flex items-center gap-1">
              <span className="font-body text-[10px] text-brand-mid-gray">Meeting</span>
              <AudioIndicator isCapturing={isCapturing} audioLevel={systemAudioLevel ?? 0} />
            </span>
          )}
          {captureStatus && (
            <span className="font-body text-xs text-brand-mid-gray">{captureStatus}</span>
          )}
          {captureError && (
            <span className="font-body text-xs text-red-600">{captureError}</span>
          )}
          <select
            value={session.meeting_type || "general"}
            onChange={(event) => {
              void onUpdateSessionContext({ meeting_type: event.target.value as MeetingType });
            }}
            disabled={postProcessingActive}
            className="rounded-md border border-brand-light-gray-1 bg-surface px-2 py-1 font-body text-xs text-brand-gray focus:border-brand-teal-light disabled:cursor-not-allowed disabled:bg-brand-light-gray-2"
            title="Conversation type"
          >
            {MEETING_TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          {session.meeting_context.trim() && (
            <button
              type="button"
              onClick={() => setContextExpanded((open) => !open)}
              title={contextExpanded ? "Collapse context" : session.meeting_context}
              className={`min-w-0 rounded-md border border-brand-light-gray-1 bg-brand-light-gray-2 px-2 py-1 text-left font-body text-xs text-brand-mid-gray transition-colors hover:text-brand-gray ${
                contextExpanded ? "w-full basis-full whitespace-pre-wrap break-words" : "max-w-xs truncate"
              }`}
            >
              {session.meeting_context.trim()}
            </button>
          )}
          <button
            type="button"
            onClick={() => setDebugOpen((open) => !open)}
            aria-expanded={debugOpen}
            className={`rounded-md border px-2 py-1 font-body text-xs font-semibold transition-colors ${
              debugOpen
                ? "border-brand-teal bg-brand-teal/10 text-brand-teal"
                : "border-brand-light-gray-1 text-brand-mid-gray hover:bg-brand-light-gray-2"
            }`}
          >
            Debug
          </button>
          {debugOpen && (
            <div className="flex min-w-0 max-w-2xl flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-brand-light-gray-1 bg-brand-light-gray-2 px-2 py-1">
              <span className="whitespace-nowrap font-body text-xs text-brand-mid-gray">
                audio sent: {audioSeconds}s / {audioStats.chunksSent} chunks
                {audioStats.chunksDropped > 0 ? `, dropped ${audioStats.chunksDropped}` : ""}
                {lastAudioAge !== null ? `, last ${lastAudioAge}s ago` : ""}
              </span>
              {backendAudioStatus && (
                <span className="min-w-0 max-w-md truncate font-body text-xs text-brand-mid-gray" title={backendAudioStatus}>
                  {backendAudioStatus}
                </span>
              )}
            </div>
          )}
        </div>

        <div className="flex flex-shrink-0 items-center gap-4">
          {(!isCapturing || status !== "connected") && (
            <button
              onClick={onResumeAudio}
              disabled={postProcessingActive || isStarting}
              className="rounded-lg border border-brand-teal px-3 py-2 font-body text-sm font-semibold text-brand-teal transition-colors hover:bg-brand-teal/10 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isStarting ? "Starting..." : "Resume Audio"}
            </button>
          )}
          {/* Session timer */}
          <div className={`flex items-center gap-2 ${backendDisconnected ? "opacity-40" : ""}`}>
            <span className="font-mono text-lg font-semibold tabular-nums text-brand-dark-gray">
              {timerDisplay}
            </span>
            {backendDisconnected && (
              <span className="font-body text-[10px] font-semibold uppercase tracking-wide text-red-600">
                not recording
              </span>
            )}
          </div>

          {/* End Call split button: primary = full drain, menu = skip briefing */}
          <div className="relative flex" ref={endMenuRef}>
            <button
              onClick={() => {
                setEndMenuOpen(false);
                onEndCall("full");
              }}
              disabled={postProcessingActive}
              className={`flex items-center gap-2 rounded-l-lg px-4 py-2 font-body text-sm font-semibold text-white transition-colors ${
                postProcessingActive
                  ? "cursor-wait bg-brand-mid-gray"
                  : "bg-red-500 hover:bg-red-600"
              }`}
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M15.75 3.75L18 6m0 0l2.25 2.25M18 6l2.25-2.25M18 6l-2.25 2.25m-10.5 6v3.75a.75.75 0 01-.75.75H3a.75.75 0 01-.75-.75V15a9.75 9.75 0 019.75-9.75h2.25"
                />
              </svg>
              {postProcessingActive ? "Ending..." : "End Call"}
            </button>
            <button
              onClick={() => setEndMenuOpen((open) => !open)}
              disabled={postProcessingActive}
              aria-haspopup="menu"
              aria-expanded={endMenuOpen}
              aria-label="More end call options"
              className={`flex items-center rounded-r-lg border-l px-2 py-2 text-white transition-colors ${
                postProcessingActive
                  ? "cursor-wait border-brand-light-gray-1 bg-brand-mid-gray"
                  : "border-red-400 bg-red-500 hover:bg-red-600"
              }`}
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
              </svg>
            </button>
            {endMenuOpen && !postProcessingActive && (
              <div
                role="menu"
                className="absolute right-0 top-full z-20 mt-1 w-64 rounded-lg border border-brand-light-gray-1 bg-surface py-1 shadow-lg"
              >
                <button
                  role="menuitem"
                  onClick={() => {
                    setEndMenuOpen(false);
                    onEndCall("skip_analysis");
                  }}
                  className="block w-full px-4 py-2.5 text-left transition-colors hover:bg-brand-light-gray-2"
                >
                  <span className="block font-body text-sm font-semibold text-brand-dark-gray">
                    End without briefing
                  </span>
                  <span className="mt-0.5 block font-body text-xs text-brand-mid-gray">
                    Saves the transcript and reconciles insights; skips the call briefing and offering matching.
                  </span>
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <AgentActivityPanel snapshot={activity} />
      {postProcessing && postProcessingActive && <PostProcessingProgress progress={postProcessing} />}
      <SynthesisSignals session={session} synthesis={synthesis} />
      {backendDisconnected ? (
        <div className="border-b border-red-200 bg-red-50 px-4 py-3 font-body text-sm font-medium text-red-700 md:px-6">
          Connection to the backend was lost. Audio is not being recorded. Use Resume Audio to reconnect.
        </div>
      ) : activity?.call.degraded ? (
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-3 font-body text-sm font-medium text-amber-900 md:px-6">
          {activity.call.degraded_reasons.join(" ")}
        </div>
      ) : null}

      {/* Two-column on desktop, stacked on mobile */}
      <div className={`flex flex-1 flex-col overflow-hidden md:flex-row ${postProcessingActive ? "pointer-events-none opacity-60" : ""}`}>
        {/* Left column: Questions */}
        <div className="flex flex-1 flex-col overflow-hidden pt-3">
          <div className="px-4 pb-2">
            <h2 className="font-display text-sm font-semibold uppercase tracking-wide text-brand-teal">
              Live Insights
            </h2>
          </div>
          <div className="flex-1 overflow-hidden">
            <QuestionList
              questions={displayQuestions}
              speakers={speakers}
              strategicSignalQuestionIds={strategicSignalQuestionIds}
              showEnhanced={Boolean(session.speaker_context_enhanced_at)}
              emptyMessage={emptyInsightMessage}
              onStar={onStarQuestion}
              onDismiss={onDismissQuestion}
              onVote={onVoteQuestion}
            />
          </div>
        </div>

        {/* Right column: Transcript (below insights on mobile) */}
        <div className="flex h-64 min-h-0 w-full flex-shrink-0 flex-col overflow-hidden border-t border-brand-light-gray-1 bg-surface pt-3 md:h-auto md:w-80 md:border-l md:border-t-0 xl:w-96">
          <TranscriptPanel transcripts={transcripts} speakers={speakers} />
        </div>
      </div>

      {/* Bottom: Directive bar */}
      <DirectiveBar onAddDirective={onAddDirective} disabled={postProcessingActive} />
    </div>
  );
}
