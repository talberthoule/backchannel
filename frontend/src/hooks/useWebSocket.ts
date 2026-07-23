import { useCallback, useRef, useState } from "react";
import type { AudioSendStats, StopDrainMode, WSMessage } from "../types";
import type { AudioTrack } from "./useAudioCapture";

export type WSStatus = "disconnected" | "connecting" | "connected" | "error";

/**
 * Manages a WebSocket connection to the backend for a single call session.
 * Handles binary frames (audio) and JSON messages (questions, transcripts, status).
 */
export function useWebSocket() {
  const [status, setStatus] = useState<WSStatus>("disconnected");
  const [messages, setMessages] = useState<WSMessage[]>([]);
  const [audioStats, setAudioStats] = useState<AudioSendStats>({
    chunksSent: 0,
    bytesSent: 0,
    chunksDropped: 0,
    lastSentAt: null,
  });
  const wsRef = useRef<WebSocket | null>(null);
  const connectionTokenRef = useRef(0);
  const stopCompletionRef = useRef<((completed: boolean) => void) | null>(null);
  const stopTimeoutRef = useRef<number | null>(null);
  const audioStatsRef = useRef<AudioSendStats>({
    chunksSent: 0,
    bytesSent: 0,
    chunksDropped: 0,
    lastSentAt: null,
  });
  const lastAudioStatsPublishRef = useRef(0);

  const resetAudioStats = useCallback(() => {
    const empty = {
      chunksSent: 0,
      bytesSent: 0,
      chunksDropped: 0,
      lastSentAt: null,
    };
    audioStatsRef.current = empty;
    lastAudioStatsPublishRef.current = 0;
    setAudioStats(empty);
  }, []);

  const publishAudioStats = useCallback((force = false) => {
    const now = Date.now();
    if (!force && now - lastAudioStatsPublishRef.current < 1000) return;
    lastAudioStatsPublishRef.current = now;
    setAudioStats({ ...audioStatsRef.current });
  }, []);

  const resolveStop = useCallback((completed: boolean) => {
    if (stopTimeoutRef.current !== null) {
      window.clearTimeout(stopTimeoutRef.current);
      stopTimeoutRef.current = null;
    }
    stopCompletionRef.current?.(completed);
    stopCompletionRef.current = null;
  }, []);

  const connect = useCallback((sessionId: string) => {
    connectionTokenRef.current += 1;
    const token = connectionTokenRef.current;

    if (wsRef.current) {
      wsRef.current.close();
    }

    setStatus("connecting");
    setMessages([]);
    resetAudioStats();

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/${sessionId}`);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      if (connectionTokenRef.current !== token) return;
      setStatus("connected");
    };

    ws.onmessage = (event: MessageEvent) => {
      if (connectionTokenRef.current !== token) return;

      if (event.data instanceof ArrayBuffer) {
        // Binary frame = audio out; ignored here, handled by caller if needed
        return;
      }

      try {
        const msg = JSON.parse(event.data as string) as WSMessage;
        setMessages((prev) => [...prev, msg]);
        if (msg.type === "status" && msg.data.state === "completed") {
          resolveStop(true);
        }
      } catch {
        console.warn("Unparseable WS message", event.data);
      }
    };

    ws.onerror = () => {
      if (connectionTokenRef.current !== token) return;
      setStatus("error");
    };

    ws.onclose = () => {
      if (connectionTokenRef.current !== token) return;
      resolveStop(false);
      setStatus("disconnected");
      wsRef.current = null;
    };
  }, [resolveStop, resetAudioStats]);

  const disconnect = useCallback(() => {
    connectionTokenRef.current += 1;
    resolveStop(false);
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setStatus("disconnected");
    publishAudioStats(true);
  }, [resolveStop, publishAudioStats]);

  const sendAudio = useCallback((data: ArrayBuffer, track: 0 | 1 = 0) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      // 1-byte track prefix: 0 = mic, 1 = system audio
      const framed = new Uint8Array(1 + data.byteLength);
      framed[0] = track;
      framed.set(new Uint8Array(data), 1);
      wsRef.current.send(framed.buffer);
      audioStatsRef.current = {
        ...audioStatsRef.current,
        chunksSent: audioStatsRef.current.chunksSent + 1,
        bytesSent: audioStatsRef.current.bytesSent + data.byteLength,
        lastSentAt: new Date().toISOString(),
      };
    } else {
      audioStatsRef.current = {
        ...audioStatsRef.current,
        chunksDropped: audioStatsRef.current.chunksDropped + 1,
      };
    }
    publishAudioStats();
  }, [publishAudioStats]);

  const sendDirective = useCallback((text: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "directive", text }));
    }
  }, []);

  const sendTrackState = useCallback((track: AudioTrack, active: boolean) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "track_state", track, active }));
    }
  }, []);

  const sendStop = useCallback((drain: StopDrainMode = "full") => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      return Promise.resolve(false);
    }

    return new Promise<boolean>((resolve) => {
      resolveStop(false);
      stopCompletionRef.current = resolve;
      stopTimeoutRef.current = window.setTimeout(() => resolveStop(false), 180000);
      // A bare stop keeps the backend's full drain; only send the drain field
      // when requesting the shorter pipeline (backward compatible).
      const payload = drain === "full" ? { type: "stop" } : { type: "stop", drain };
      wsRef.current?.send(JSON.stringify(payload));
    });
  }, [resolveStop]);

  return { connect, disconnect, sendAudio, sendDirective, sendTrackState, sendStop, status, messages, audioStats };
}
