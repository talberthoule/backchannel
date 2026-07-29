import { useCallback, useEffect, useState } from "react";
import type { CallSegment, Directive, Document, Question, Session, SessionSynthesis, Speaker, TranscriptEntry } from "../types";
import {
  getSynthesis,
  getSession,
  listDirectives,
  listDocuments,
  listQuestions,
  listSegments,
  listSpeakers,
  listTranscripts,
} from "../services/api";

export { reconcileRefusedSession } from "../lib/callRefusal";

export function useSession(sessionId: string | null) {
  const [session, setSession] = useState<Session | null>(null);
  const [directives, setDirectives] = useState<Directive[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [segments, setSegments] = useState<CallSegment[]>([]);
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [transcripts, setTranscripts] = useState<TranscriptEntry[]>([]);
  const [synthesis, setSynthesis] = useState<SessionSynthesis | null>(null);
  const [liveSynthesis, setLiveSynthesis] = useState<SessionSynthesis | null>(null);
  const [loading, setLoading] = useState(false);

  const refreshSession = useCallback(async () => {
    if (!sessionId) return;
    const data = await getSession(sessionId);
    setSession(data);
  }, [sessionId]);

  const refreshDirectives = useCallback(async () => {
    if (!sessionId) return;
    setDirectives(await listDirectives(sessionId));
  }, [sessionId]);

  const refreshDocuments = useCallback(async () => {
    if (!sessionId) return;
    setDocuments(await listDocuments(sessionId));
  }, [sessionId]);

  const refreshQuestions = useCallback(async () => {
    if (!sessionId) return;
    setQuestions(await listQuestions(sessionId));
  }, [sessionId]);

  const refreshSegments = useCallback(async () => {
    if (!sessionId) return;
    setSegments(await listSegments(sessionId));
  }, [sessionId]);

  const refreshSpeakers = useCallback(async () => {
    if (!sessionId) return;
    setSpeakers(await listSpeakers(sessionId));
  }, [sessionId]);

  const refreshTranscripts = useCallback(async () => {
    if (!sessionId) return;
    setTranscripts(await listTranscripts(sessionId));
  }, [sessionId]);

  const refreshSynthesis = useCallback(async (mode = "post_call") => {
    if (!sessionId) return;
    const data = await getSynthesis(sessionId, mode);
    if (mode === "live") {
      setLiveSynthesis(data);
    } else {
      setSynthesis(data);
    }
    return data;
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) {
      setSession(null);
      setDirectives([]);
      setDocuments([]);
      setQuestions([]);
      setSegments([]);
      setSpeakers([]);
      setTranscripts([]);
      setSynthesis(null);
      setLiveSynthesis(null);
      return;
    }

    let cancelled = false;
    setSession(null);
    setDirectives([]);
    setDocuments([]);
    setQuestions([]);
    setSegments([]);
    setSpeakers([]);
    setTranscripts([]);
    setSynthesis(null);
    setLiveSynthesis(null);

    const loadAll = async () => {
      setLoading(true);
      try {
        const [sess, dirs, docs, qs, segs, spkrs, txs, synth, liveSynth] = await Promise.all([
          getSession(sessionId),
          listDirectives(sessionId),
          listDocuments(sessionId),
          listQuestions(sessionId),
          listSegments(sessionId),
          listSpeakers(sessionId),
          listTranscripts(sessionId),
          getSynthesis(sessionId),
          getSynthesis(sessionId, "live"),
        ]);
        if (cancelled) return;
        setSession(sess);
        setDirectives(dirs);
        setDocuments(docs);
        setQuestions(qs);
        setSegments(segs);
        setSpeakers(spkrs);
        setTranscripts(txs);
        setSynthesis(synth);
        setLiveSynthesis(liveSynth);
      } catch (err) {
        console.error("Failed to load session data", err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    loadAll();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  return {
    session,
    directives,
    documents,
    questions,
    setQuestions,
    segments,
    speakers,
    transcripts,
    synthesis,
    liveSynthesis,
    loading,
    refreshSession,
    refreshDirectives,
    refreshDocuments,
    refreshQuestions,
    refreshSegments,
    refreshSpeakers,
    refreshTranscripts,
    refreshSynthesis,
  };
}
