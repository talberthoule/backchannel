import { useCallback, useEffect, useRef, useState } from "react";

const RECORDING_MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
];

function getRecorderOptions(): MediaRecorderOptions {
  const mimeType = RECORDING_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
  return mimeType ? { mimeType } : {};
}

function createRecordedFile(chunks: BlobPart[], mimeType: string, baseName: string): File {
  const type = mimeType || "audio/webm";
  const extension = type.includes("mp4") ? "m4a" : "webm";
  return new File([new Blob(chunks, { type })], `${baseName}.${extension}`, { type });
}

interface UseClipRecorderOptions {
  maxSeconds: number;
  baseName: string;
  onClip: (file: File) => void;
  onError?: (message: string) => void;
}

/**
 * Records a short mic clip and hands the finished File to onClip. A generation
 * guard ignores late callbacks from a superseded recording, and everything is
 * torn down on unmount so a stopped recorder never keeps the mic open.
 */
export function useClipRecorder({ maxSeconds, baseName, onClip, onError }: UseClipRecorderOptions) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<number | null>(null);
  const generationRef = useRef(0);

  const supported =
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined";

  const clearTimer = useCallback(() => {
    if (timerRef.current != null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const stopTracks = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
  }, []);

  useEffect(() => () => {
    generationRef.current += 1;
    const recorder = recorderRef.current;
    if (recorder) {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      if (recorder.state === "recording") recorder.stop();
    }
    clearTimer();
    stopTracks();
  }, [clearTimer, stopTracks]);

  const start = useCallback(async () => {
    if (!supported) {
      onError?.("Browser microphone recording is not available.");
      return;
    }
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (generation !== generationRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const recorder = new MediaRecorder(stream, getRecorderOptions());
      streamRef.current = stream;
      recorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        if (generation !== generationRef.current) return;
        const file = createRecordedFile(chunksRef.current, recorder.mimeType, baseName);
        stopTracks();
        clearTimer();
        setRecording(false);
        setSeconds(0);
        onClip(file);
      };

      recorder.start();
      setRecording(true);
      setSeconds(0);
      timerRef.current = window.setInterval(() => {
        setSeconds((prev) => {
          const next = prev + 1;
          if (next >= maxSeconds && recorder.state === "recording") recorder.stop();
          return next;
        });
      }, 1000);
    } catch (err) {
      if (generation !== generationRef.current) return;
      onError?.(err instanceof Error ? err.message : "Unable to start microphone recording.");
      stopTracks();
      clearTimer();
      setRecording(false);
    }
  }, [supported, maxSeconds, baseName, onClip, onError, stopTracks, clearTimer]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder?.state === "recording") recorder.stop();
  }, []);

  return { supported, recording, seconds, start, stop };
}
