import { useCallback, useEffect, useRef, useState } from "react";
import Layout from "./components/Layout";
import NewSessionModal from "./components/NewSessionModal";
import AdminPanel from "./components/AdminPanel";
import OfferingsManager from "./components/OfferingsManager";
import KnowledgeManager from "./components/KnowledgeManager";
import PreCallView from "./components/PreCall/PreCallView";
import ActiveCallView from "./components/ActiveCall/ActiveCallView";
import PostCallView from "./components/PostCall/PostCallView";
import { useAudioCapture } from "./hooks/useAudioCapture";
import { useWebSocket } from "./hooks/useWebSocket";
import { useSession } from "./hooks/useSession";
import { useSpeechRecognition } from "./hooks/useSpeechRecognition";
import * as api from "./services/api";
import type { PostProcessingProgress, Question, Session, SessionGroup, SessionSynthesis, TranscriptEntry, WSStatusData } from "./types";

function idlePostProcessing(): PostProcessingProgress {
  return {
    active: false,
    state: "idle",
    stage: "",
    message: "",
    currentStep: 0,
    totalSteps: 5,
    progress: 0,
    startedAt: null,
    completedAt: null,
    confirmed: false,
  };
}

function startPostProcessing(): PostProcessingProgress {
  return {
    active: true,
    state: "running",
    stage: "stopping_audio",
    message: "Stopping audio capture...",
    currentStep: 0,
    totalSteps: 5,
    progress: 5,
    startedAt: new Date().toISOString(),
    completedAt: null,
    confirmed: false,
  };
}

function progressFromStatus(prev: PostProcessingProgress, data: WSStatusData): PostProcessingProgress {
  return {
    active: true,
    state: "running",
    stage: data.stage ?? prev.stage,
    message: data.message || prev.message,
    currentStep: data.current_step ?? prev.currentStep,
    totalSteps: data.total_steps ?? prev.totalSteps,
    progress: data.progress ?? prev.progress,
    startedAt: prev.startedAt ?? new Date().toISOString(),
    completedAt: null,
    confirmed: false,
    details: data.details ?? prev.details,
  };
}

function completePostProcessing(
  prev: PostProcessingProgress,
  message = "Post-processing complete",
  details?: Record<string, unknown>,
): PostProcessingProgress {
  return {
    ...prev,
    active: false,
    state: "completed",
    stage: "complete",
    message,
    currentStep: prev.totalSteps,
    progress: 100,
    completedAt: new Date().toISOString(),
    confirmed: true,
    details: details ?? prev.details,
  };
}

function unconfirmedPostProcessing(prev: PostProcessingProgress): PostProcessingProgress {
  return {
    ...prev,
    active: false,
    state: "timeout",
    message: "Post-processing completion was not confirmed. Retry ending the call or refresh before editing speakers or enhancing insights.",
    progress: Math.max(prev.progress, 90),
    completedAt: null,
    confirmed: false,
  };
}

function transcriptKey(entry: TranscriptEntry): string {
  if (entry.id) return `id:${entry.id}`;
  if (entry.sequence !== undefined) return `seq:${entry.session_id || ""}:${entry.sequence}`;
  return `raw:${entry.timestamp}:${entry.speaker_id || ""}:${entry.text}`;
}

function mergeTranscripts(...groups: TranscriptEntry[][]): TranscriptEntry[] {
  const seen = new Set<string>();
  const merged: TranscriptEntry[] = [];
  for (const group of groups) {
    for (const entry of group) {
      const key = transcriptKey(entry);
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push(entry);
    }
  }
  return merged.sort((a, b) => {
    if (a.sequence !== undefined && b.sequence !== undefined) return a.sequence - b.sequence;
    return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
  });
}

function mergeQuestions(primary: Question[], secondary: Question[]): Question[] {
  const seen = new Set<string>();
  const merged: Question[] = [];
  for (const group of [primary, secondary]) {
    for (const question of group) {
      if (seen.has(question.id)) continue;
      seen.add(question.id);
      merged.push(question);
    }
  }
  return merged;
}

function synthesisTime(synthesis: SessionSynthesis | null): number {
  if (!synthesis) return 0;
  return new Date(synthesis.updated_at || synthesis.created_at).getTime();
}

function newestSynthesis(
  mode: "live" | "post_call",
  ...items: (SessionSynthesis | null)[]
): SessionSynthesis | null {
  return items
    .filter((item): item is SessionSynthesis => item?.mode === mode)
    .sort((a, b) => synthesisTime(b) - synthesisTime(a))[0] || null;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export default function App() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [groups, setGroups] = useState<SessionGroup[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [showOfferings, setShowOfferings] = useState(false);
  const [showKnowledge, setShowKnowledge] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);
  const [showNewSession, setShowNewSession] = useState(false);

  const {
    session,
    directives,
    documents,
    questions: savedQuestions,
    segments,
    speakers,
    transcripts: savedTranscripts,
    synthesis: savedSynthesis,
    liveSynthesis: savedLiveSynthesis,
    refreshSession,
    refreshDirectives,
    refreshDocuments,
    refreshQuestions,
    refreshSegments,
    refreshSpeakers,
    refreshTranscripts,
    refreshSynthesis,
  } = useSession(activeSessionId);

  const { startCapture, stopCapture, isCapturing, audioLevel, systemAudioLevel, systemAudioActive } = useAudioCapture();
  const [captureSystemAudio, setCaptureSystemAudio] = useState(true);
  const { connect, disconnect, sendAudio, sendDirective, sendStop, status, messages, audioStats } =
    useWebSocket();
  const { startListening, stopListening } = useSpeechRecognition();

  const [liveQuestions, setLiveQuestions] = useState<Question[]>([]);
  const [liveTranscripts, setLiveTranscripts] = useState<TranscriptEntry[]>([]);
  const [interimText, setInterimText] = useState("");
  const [runtimeSynthesis, setRuntimeSynthesis] = useState<SessionSynthesis | null>(null);
  const [processingTranscript, setProcessingTranscript] = useState(false);
  const [processingError, setProcessingError] = useState<string | null>(null);
  const [backendAudioStatus, setBackendAudioStatus] = useState<string | null>(null);
  const [captureError, setCaptureError] = useState<string | null>(null);
  // Track when the current call segment started (resets on each start/resume)
  const [callSegmentStart, setCallSegmentStart] = useState<string | null>(null);
  const [postProcessing, setPostProcessing] = useState<PostProcessingProgress>(() => idlePostProcessing());

  useEffect(() => {
    api.listSessions().then(setSessions).catch(console.error);
    api.listGroups().then(setGroups).catch(console.error);
  }, []);

  // Process incoming WebSocket messages — questions and transcripts
  const processedCount = useRef(0);
  useEffect(() => {
    const newMessages = messages.slice(processedCount.current);
    processedCount.current = messages.length;

    for (const msg of newMessages) {
      if (msg.type === "question") {
        const q: Question = {
          id: msg.data.id,
          session_id: activeSessionId || "",
          item_type: (msg.data.item_type as any) || "question",
          question: msg.data.question,
          rationale: msg.data.rationale,
          source_context: msg.data.source_context,
          speaker_id: msg.data.speaker_id ?? null,
          directive_id: msg.data.directive_id,
          starred: false,
          dismissed: false,
          created_at: msg.data.timestamp,
          answered: false,
          answer_summary: "",
          needs_followup: false,
          followup_question: "",
          is_followup: msg.data.is_followup || false,
          agent_source: msg.data.agent_source,
          offering_match: msg.data.offering_match || "",
          vote: msg.data.vote ?? 0,
          enhanced: msg.data.enhanced ?? false,
        };
        setLiveQuestions((prev) => [q, ...prev]);
      } else if (msg.type === "question_answered") {
        setLiveQuestions((prev) =>
          prev.map((q) =>
            q.id === msg.data.id
              ? {
                  ...q,
                  answered: true,
                  answer_summary: msg.data.answer_summary,
                  needs_followup: msg.data.needs_followup,
                  followup_question: msg.data.followup_question,
                }
              : q
          )
        );
      } else if (msg.type === "transcript") {
        // Diarized transcript arrived from backend — clear interim text since this replaces it
        setInterimText("");
        setLiveTranscripts((prev) => [...prev, msg.data]);
        if (msg.data.speaker_id && !speakers.some((s) => s.id === msg.data.speaker_id)) {
          void refreshSpeakers();
        }
      } else if (msg.type === "interim_transcript") {
        // Live API real-time transcription — show instantly as interim preview
        // Append new text, but cap length to avoid unbounded growth between batches
        setInterimText((prev) => {
          const combined = prev + msg.data.text;
          return combined.length > 500 ? combined.slice(-500) : combined;
        });
      } else if (msg.type === "status") {
        if (msg.data.state === "post_processing" || msg.data.state === "finalizing") {
          setPostProcessing((prev) => progressFromStatus(prev, msg.data));
        } else if (msg.data.state === "completed") {
          setPostProcessing((prev) => completePostProcessing(prev, msg.data.message, msg.data.details));
        } else if (msg.data.state === "error") {
          setPostProcessing((prev) => ({
            ...prev,
            active: false,
            state: "error",
            message: msg.data.message || "Post-processing failed.",
            completedAt: null,
            confirmed: false,
          }));
        } else if (
          msg.data.state === "audio_received" ||
          msg.data.state === "audio_segment" ||
          msg.data.state === "transcript_saved"
        ) {
          setBackendAudioStatus(msg.data.message);
        }
      } else if (msg.type === "insight_updated" || msg.type === "insight_elevated") {
        const d = msg.data;
        setLiveQuestions((prev) => {
          const exists = prev.some((q) => q.id === d.id);
          if (exists) {
            return prev.map((q) =>
              q.id === d.id
                ? {
                    ...q,
                    item_type: d.item_type || q.item_type,
                    question: d.question || q.question,
                    rationale: d.rationale || q.rationale,
                    source_context: d.source_context || q.source_context,
                    speaker_id: d.speaker_id ?? q.speaker_id,
                    answered: d.answered ?? q.answered,
                    answer_summary: d.answer_summary || q.answer_summary,
                    needs_followup: d.needs_followup ?? q.needs_followup,
                    followup_question: d.followup_question || q.followup_question,
                    dismissed: d.dismissed ?? q.dismissed,
                    enrichment_notes: d.enrichment_notes || q.enrichment_notes,
                    revision_count: d.revision_count ?? q.revision_count,
                    updated_at: d.updated_at || new Date().toISOString(),
                    agent_source: d.agent_source || q.agent_source,
                    offering_match: d.offering_match || q.offering_match,
                    vote: d.vote ?? q.vote,
                    enhanced: d.enhanced ?? q.enhanced,
                  }
                : q
            );
          }
          return prev;
        });
      } else if (msg.type === "synthesis_updated") {
        setRuntimeSynthesis(msg.data);
      }
    }
  }, [messages, activeSessionId, speakers, refreshSpeakers]);

  const allQuestions = session?.state === "completed"
    ? mergeQuestions(savedQuestions, liveQuestions)
    : mergeQuestions(liveQuestions, savedQuestions);

  const persistedAndLiveTranscripts = mergeTranscripts(savedTranscripts, liveTranscripts);

  // Combine final transcripts + current interim for display
  const displayTranscripts: TranscriptEntry[] = [
    ...persistedAndLiveTranscripts,
    ...(interimText
      ? [{ text: interimText, timestamp: new Date().toISOString() }]
      : []),
  ];
  const reviewTranscripts = persistedAndLiveTranscripts;
  const liveSynthesis = newestSynthesis("live", savedLiveSynthesis, runtimeSynthesis);
  const postCallSynthesis = newestSynthesis("post_call", savedSynthesis, runtimeSynthesis);

  const refreshSessions = useCallback(async () => {
    const s = await api.listSessions();
    setSessions(s);
  }, []);

  const refreshGroups = useCallback(async () => {
    const g = await api.listGroups();
    setGroups(g);
  }, []);

  const resetSessionRuntimeState = useCallback(() => {
    setLiveQuestions([]);
    setLiveTranscripts([]);
    setInterimText("");
    setRuntimeSynthesis(null);
    setProcessingTranscript(false);
    setProcessingError(null);
    setBackendAudioStatus(null);
    setCaptureError(null);
    setCallSegmentStart(null);
    setPostProcessing(idlePostProcessing());
    processedCount.current = messages.length;
  }, [messages.length]);

  const handleNewSession = useCallback(() => {
    setShowNewSession(true);
  }, []);

  const handleCreateSession = useCallback(async (name: string, meetingType: Session["meeting_type"]) => {
    const s = await api.createSession(name, { meeting_type: meetingType });
    await refreshSessions();
    resetSessionRuntimeState();
    setActiveSessionId(s.id);
    setShowNewSession(false);
    setShowOfferings(false);
    setShowKnowledge(false);
    setShowAdmin(false);
  }, [refreshSessions, resetSessionRuntimeState]);

  const handleSelectSession = useCallback((id: string) => {
    resetSessionRuntimeState();
    setActiveSessionId(id);
    setShowOfferings(false);
    setShowKnowledge(false);
    setShowAdmin(false);
  }, [resetSessionRuntimeState]);

  const handleOpenOfferings = useCallback(() => {
    resetSessionRuntimeState();
    setShowOfferings(true);
    setShowKnowledge(false);
    setShowAdmin(false);
    setActiveSessionId(null);
  }, [resetSessionRuntimeState]);

  const handleOpenKnowledge = useCallback(() => {
    resetSessionRuntimeState();
    setShowKnowledge(true);
    setShowOfferings(false);
    setShowAdmin(false);
    setActiveSessionId(null);
  }, [resetSessionRuntimeState]);

  const handleOpenAdmin = useCallback(() => {
    resetSessionRuntimeState();
    setShowAdmin(true);
    setShowOfferings(false);
    setShowKnowledge(false);
    setActiveSessionId(null);
  }, [resetSessionRuntimeState]);

  const handleRenameSession = useCallback(async (name: string) => {
    if (!activeSessionId) return;
    await api.updateSession(activeSessionId, { name });
    await refreshSession();
    await refreshSessions();
  }, [activeSessionId, refreshSession, refreshSessions]);

  const handleUpdateSessionContext = useCallback(async (data: { meeting_type?: Session["meeting_type"]; meeting_context?: string }) => {
    if (!activeSessionId) return;
    await api.updateSession(activeSessionId, data);
    await refreshSession();
    await refreshSessions();
  }, [activeSessionId, refreshSession, refreshSessions]);

  const handleDeleteSession = useCallback(async () => {
    if (!activeSessionId) return;
    if (!confirm("Delete this session and all its data?")) return;
    await api.deleteSession(activeSessionId);
    setActiveSessionId(null);
    resetSessionRuntimeState();
    await refreshSessions();
  }, [activeSessionId, refreshSessions, resetSessionRuntimeState]);

  const handleDeleteSessionById = useCallback(async (sessionId: string) => {
    await api.deleteSession(sessionId);
    if (sessionId === activeSessionId) {
      setActiveSessionId(null);
      resetSessionRuntimeState();
    }
    await refreshSessions();
  }, [activeSessionId, refreshSessions, resetSessionRuntimeState]);

  const activeSessionIdRef = useRef(activeSessionId);
  activeSessionIdRef.current = activeSessionId;

  const startAudioFeed = useCallback(async (sessionId: string, reconnect = false) => {
    setCaptureError(null);
    if (reconnect || status !== "connected") {
      connect(sessionId);
      await delay(500);
    }

    try {
      // ponytail: getDisplayMedia needs a recent user gesture; if the prompt
      // is blocked or declined we proceed mic-only.
      await startCapture((chunk, track) => {
        sendAudio(chunk, track);
      }, undefined, { systemAudio: captureSystemAudio });
    } catch (err) {
      const message = errorMessage(err, "Microphone capture failed.");
      setCaptureError(message);
      console.error("Failed to start audio capture", err);
    }
  }, [connect, sendAudio, startCapture, status, captureSystemAudio]);

  const beginCall = useCallback(async () => {
    if (!activeSessionId) return;

    await api.updateSession(activeSessionId, { state: "active" });
    await refreshSession();
    await refreshSessions();

    setLiveQuestions([]);
    setLiveTranscripts([]);
    setInterimText("");
    setRuntimeSynthesis(null);
    setProcessingTranscript(false);
    setProcessingError(null);
    setBackendAudioStatus(null);
    setCaptureError(null);
    setCallSegmentStart(new Date().toISOString());
    setPostProcessing(idlePostProcessing());
    processedCount.current = messages.length;

    // Auto-create default speakers if none exist
    let currentSpeakers = speakers;
    if (currentSpeakers.length === 0) {
      await api.createSpeaker(activeSessionId, { name: "Me / Team Member", role: "", color: "#0d9488", is_user: true, speaker_type: "team" });
      await api.createSpeaker(activeSessionId, { name: "Participant 1", role: "", color: "#f59e0b", is_user: false, speaker_type: "external" });
      await refreshSpeakers();
      currentSpeakers = await api.listSpeakers(activeSessionId);
    }

    // Connect WebSocket (audio → backend for diarization + Gemini for questions)
    await startAudioFeed(activeSessionId, true);
  }, [activeSessionId, startAudioFeed, startListening, refreshSession, refreshSessions, speakers, refreshSpeakers, messages.length]);

  const handleStartCall = useCallback(() => beginCall(), [beginCall]);

  const handleResumeAudio = useCallback(async () => {
    if (!activeSessionId) return;
    if (isCapturing) {
      stopCapture();
    }
    setCallSegmentStart((current) => current ?? new Date().toISOString());
    await startAudioFeed(activeSessionId, status !== "connected");
  }, [activeSessionId, isCapturing, startAudioFeed, status, stopCapture]);

  const handleProcessTranscript = useCallback(async () => {
    if (!activeSessionId) return;
    setProcessingTranscript(true);
    setProcessingError(null);
    try {
      await api.analyzeSession(activeSessionId);
      try {
        const synthesis = await api.refreshSynthesis(activeSessionId);
        setRuntimeSynthesis(synthesis);
      } catch (err) {
        setProcessingError(errorMessage(err, "Transcript analysis completed, but briefing generation failed."));
      }
    } catch (err) {
      setProcessingError(errorMessage(err, "Transcript analysis failed."));
    } finally {
      await Promise.allSettled([
        refreshSession(),
        refreshQuestions(),
        refreshSegments(),
        refreshTranscripts(),
        refreshSynthesis(),
        refreshSessions(),
      ]);
      setProcessingTranscript(false);
    }
  }, [activeSessionId, refreshSession, refreshQuestions, refreshSegments, refreshTranscripts, refreshSynthesis, refreshSessions]);

  const handleResumeCall = useCallback(async () => {
    if (!activeSessionId) return;
    await refreshQuestions();
    await beginCall();
  }, [activeSessionId, refreshQuestions, beginCall]);

  const handleEndCall = useCallback(async () => {
    setPostProcessing(startPostProcessing());
    stopCapture();
    stopListening();
    const backendCompleted = await sendStop();
    disconnect();
    setInterimText("");

    if (activeSessionId) {
      let completionConfirmed = backendCompleted;
      if (!completionConfirmed) {
        try {
          const latestSession = await api.getSession(activeSessionId);
          completionConfirmed = latestSession.state === "completed" && !!latestSession.ended_at;
        } catch (err) {
          console.error("Failed to confirm post-processing completion", err);
        }
      }

      if (completionConfirmed) {
        setPostProcessing((prev) => completePostProcessing(prev));
      } else {
        setPostProcessing((prev) => unconfirmedPostProcessing(prev));
      }
      await refreshSession();
      await refreshQuestions();
      await refreshSegments();
      await refreshSpeakers();
      await refreshTranscripts();
      await refreshSynthesis();
      await refreshSessions();
    }
  }, [activeSessionId, sendStop, stopCapture, stopListening, disconnect, refreshSession, refreshQuestions, refreshSegments, refreshSpeakers, refreshTranscripts, refreshSynthesis, refreshSessions]);

  const handleStarQuestion = useCallback(
    async (questionId: string, starred: boolean) => {
      if (!activeSessionId) return;
      await api.updateQuestion(activeSessionId, questionId, { starred });
      setLiveQuestions((prev) =>
        prev.map((q) => (q.id === questionId ? { ...q, starred } : q))
      );
      await refreshQuestions();
    },
    [activeSessionId, refreshQuestions]
  );

  const handleVoteQuestion = useCallback(
    async (questionId: string, vote: number) => {
      if (!activeSessionId) return;
      await api.updateQuestion(activeSessionId, questionId, { vote } as any);
      setLiveQuestions((prev) =>
        prev.map((q) => (q.id === questionId ? { ...q, vote } : q))
      );
      await refreshQuestions();
    },
    [activeSessionId, refreshQuestions]
  );

  const handleDismissQuestion = useCallback(
    async (questionId: string) => {
      if (!activeSessionId) return;
      await api.updateQuestion(activeSessionId, questionId, { dismissed: true });
      setLiveQuestions((prev) =>
        prev.map((q) => (q.id === questionId ? { ...q, dismissed: true } : q))
      );
      await refreshQuestions();
    },
    [activeSessionId, refreshQuestions]
  );

  const handleAddDirective = useCallback(
    async (text: string) => {
      if (!activeSessionId) return;
      if (session?.state === "active") {
        sendDirective(text);
      }
      await refreshDirectives();
    },
    [activeSessionId, session?.state, sendDirective, refreshDirectives]
  );

  const renderContent = () => {
    if (showAdmin) {
      return <AdminPanel onBack={() => setShowAdmin(false)} />;
    }

    if (showOfferings) {
      return <OfferingsManager onBack={() => setShowOfferings(false)} />;
    }

    if (showKnowledge) {
      return <KnowledgeManager onBack={() => setShowKnowledge(false)} />;
    }

    if (!session) {
      return (
        <div className="flex items-center justify-center h-full text-brand-mid-gray">
          <div className="text-center">
            <h2 className="text-2xl font-display font-semibold mb-2">Welcome to Backchannel</h2>
            <p className="font-body">Select a session from the sidebar or create a new one to get started.</p>
          </div>
        </div>
      );
    }

    switch (session.state) {
      case "pre_call":
        return (
          <PreCallView
            session={session}
            directives={directives}
            documents={documents}
            speakers={speakers}
            transcriptCount={savedTranscripts.length}
            processingTranscript={processingTranscript}
            processingError={processingError}
            onStartCall={handleStartCall}
            captureSystemAudio={captureSystemAudio}
            onToggleSystemAudio={setCaptureSystemAudio}
            onProcessTranscript={handleProcessTranscript}
            onRefreshDirectives={refreshDirectives}
            onRefreshDocuments={refreshDocuments}
            onRefreshSpeakers={refreshSpeakers}
            onRefreshTranscripts={refreshTranscripts}
            onRenameSession={handleRenameSession}
            onUpdateSessionContext={handleUpdateSessionContext}
          />
        );
      case "active":
        return (
          <ActiveCallView
            session={session}
            questions={allQuestions}
            transcripts={displayTranscripts}
            onEndCall={handleEndCall}
            onResumeAudio={handleResumeAudio}
            onStarQuestion={handleStarQuestion}
            onDismissQuestion={handleDismissQuestion}
            onVoteQuestion={handleVoteQuestion}
            onAddDirective={handleAddDirective}
            onUpdateSessionContext={handleUpdateSessionContext}
            audioLevel={audioLevel}
            systemAudioLevel={systemAudioLevel}
            systemAudioActive={systemAudioActive}
            isCapturing={isCapturing}
            audioStats={audioStats}
            backendAudioStatus={backendAudioStatus}
            captureError={captureError}
            status={status}
            callSegmentStart={callSegmentStart}
            speakers={speakers}
            postProcessing={postProcessing}
            synthesis={liveSynthesis}
          />
        );
      case "completed":
        return (
          <PostCallView
            session={session}
            questions={allQuestions}
            transcripts={reviewTranscripts}
            directives={directives}
            documents={documents}
            segments={segments}
            speakers={speakers}
            synthesis={postCallSynthesis}
            onResumeCall={handleResumeCall}
            onDeleteSession={handleDeleteSession}
            onRefreshSpeakers={refreshSpeakers}
            onRefreshSession={refreshSession}
            onRefreshQuestions={refreshQuestions}
            onRefreshSynthesis={refreshSynthesis}
            onRenameSession={handleRenameSession}
            onRetranscribed={async () => {
              setLiveTranscripts([]);
              await Promise.all([refreshTranscripts(), refreshSpeakers(), refreshSegments()]);
            }}
            postProcessing={postProcessing}
          />
        );
      default:
        return null;
    }
  };

  return (
    <Layout
      sessions={sessions}
      groups={groups}
      activeSessionId={activeSessionId}
      onSelectSession={handleSelectSession}
      onNewSession={handleNewSession}
      onOpenOfferings={handleOpenOfferings}
      onOpenKnowledge={handleOpenKnowledge}
      onOpenAdmin={handleOpenAdmin}
      showingOfferings={showOfferings}
      showingKnowledge={showKnowledge}
      showingAdmin={showAdmin}
      onDeleteSession={handleDeleteSessionById}
      onRefreshGroups={refreshGroups}
      onRefreshSessions={refreshSessions}
    >
      {renderContent()}
      <NewSessionModal
        open={showNewSession}
        onClose={() => setShowNewSession(false)}
        onCreate={handleCreateSession}
      />
    </Layout>
  );
}
