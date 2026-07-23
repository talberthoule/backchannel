import { useCallback, useEffect, useRef, useState } from "react";

export type AudioTrack = 0 | 1; // 0 = mic, 1 = system audio

interface CaptureOptions {
  systemAudio?: boolean;
  onSystemAudioStateChange?: (active: boolean) => void;
}

export const MIC_ONLY_AUDIO_CONSTRAINTS: MediaTrackConstraints = {
  channelCount: 1,
  echoCancellation: false,
  noiseSuppression: false,
  autoGainControl: true,
};

export function startSingleFlight<T>(
  inFlight: { current: Promise<T> | null },
  operation: () => Promise<T>,
): Promise<T> {
  if (inFlight.current) return inFlight.current;

  const pending = operation();
  inFlight.current = pending;
  const clear = () => {
    if (inFlight.current === pending) inFlight.current = null;
  };
  pending.then(clear, clear);
  return pending;
}

const WORKLET_CODE = `
  class PCM16Processor extends AudioWorkletProcessor {
    constructor() {
      super();
      this._buffer = [];
      this._samplesNeeded = 1600; // ~100ms at 16kHz
    }
    process(inputs) {
      const input = inputs[0];
      if (!input || !input[0]) return true;
      const float32 = input[0];
      for (let i = 0; i < float32.length; i++) {
        const s = Math.max(-1, Math.min(1, float32[i]));
        this._buffer.push(s < 0 ? s * 0x8000 : s * 0x7fff);
      }
      if (this._buffer.length >= this._samplesNeeded) {
        const int16 = new Int16Array(this._buffer.splice(0, this._samplesNeeded));
        this.port.postMessage(int16.buffer, [int16.buffer]);
      }
      return true;
    }
  }
  registerProcessor('pcm16-processor', PCM16Processor);
`;

/**
 * Captures microphone audio (and optionally tab/system audio) as PCM16 16kHz
 * mono chunks delivered via callback with a track id.
 */
export function useAudioCapture() {
  const [isCapturing, setIsCapturing] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [systemAudioLevel, setSystemAudioLevel] = useState(0);
  const [systemAudioActive, setSystemAudioActive] = useState(false);

  const streamsRef = useRef<MediaStream[]>([]);
  const contextRef = useRef<AudioContext | null>(null);
  const nodesRef = useRef<AudioNode[]>([]);
  const analysersRef = useRef<{ analyser: AnalyserNode; track: AudioTrack }[]>([]);
  const levelFrameRef = useRef<number>(0);
  const onLevelRef = useRef<((level: number) => void) | null>(null);
  const onSystemAudioStateChangeRef = useRef<((active: boolean) => void) | null>(null);
  const workletReadyRef = useRef(false);
  const startPromiseRef = useRef<Promise<void> | null>(null);
  const captureGenerationRef = useRef(0);

  useEffect(() => {
    const resumeContext = () => {
      if (document.visibilityState === "visible" && contextRef.current?.state === "suspended") {
        void contextRef.current.resume();
      }
    };
    document.addEventListener("visibilitychange", resumeContext);
    window.addEventListener("focus", resumeContext);
    return () => {
      document.removeEventListener("visibilitychange", resumeContext);
      window.removeEventListener("focus", resumeContext);
    };
  }, []);

  const releaseCapture = useCallback(() => {
    cancelAnimationFrame(levelFrameRef.current);
    setAudioLevel(0);
    setSystemAudioLevel(0);
    setSystemAudioActive(false);
    onLevelRef.current = null;
    onSystemAudioStateChangeRef.current = null;

    for (const node of nodesRef.current) {
      node.disconnect();
    }
    nodesRef.current = [];
    analysersRef.current = [];

    if (contextRef.current) {
      void contextRef.current.close();
      contextRef.current = null;
    }
    for (const stream of streamsRef.current) {
      stream.getTracks().forEach((track) => track.stop());
    }
    streamsRef.current = [];

    setIsCapturing(false);
  }, []);

  const attachPipeline = useCallback(async (
    ctx: AudioContext,
    stream: MediaStream,
    track: AudioTrack,
    onChunk: (chunk: ArrayBuffer, track: AudioTrack) => void,
  ) => {
    const source = ctx.createMediaStreamSource(stream);
    const silentSink = ctx.createGain();
    silentSink.gain.value = 0;
    silentSink.connect(ctx.destination);

    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    analysersRef.current.push({ analyser, track });

    try {
      if (!workletReadyRef.current) {
        const blob = new Blob([WORKLET_CODE], { type: "application/javascript" });
        const url = URL.createObjectURL(blob);
        await ctx.audioWorklet.addModule(url);
        URL.revokeObjectURL(url);
        workletReadyRef.current = true;
      }
      const workletNode = new AudioWorkletNode(ctx, "pcm16-processor");
      workletNode.port.onmessage = (e: MessageEvent) => {
        onChunk(e.data as ArrayBuffer, track);
      };
      source.connect(workletNode);
      workletNode.connect(silentSink); // required for processing to run
      nodesRef.current.push(workletNode);
    } catch {
      // Fallback: ScriptProcessorNode
      const scriptNode = ctx.createScriptProcessor(4096, 1, 1);
      let pcmBuffer: number[] = [];
      const samplesPerChunk = 1600; // ~100ms at 16kHz

      scriptNode.onaudioprocess = (e: AudioProcessingEvent) => {
        const float32 = e.inputBuffer.getChannelData(0);
        for (let i = 0; i < float32.length; i++) {
          const s = Math.max(-1, Math.min(1, float32[i]));
          pcmBuffer.push(s < 0 ? s * 0x8000 : s * 0x7fff);
        }
        while (pcmBuffer.length >= samplesPerChunk) {
          const samples = pcmBuffer.splice(0, samplesPerChunk);
          const int16 = new Int16Array(samples);
          onChunk(int16.buffer, track);
        }
      };

      source.connect(scriptNode);
      scriptNode.connect(silentSink);
      nodesRef.current.push(scriptNode);
    }
  }, []);

  const startCapture = useCallback((
    onChunk: (chunk: ArrayBuffer, track: AudioTrack) => void,
    onLevel?: (level: number) => void,
    options?: CaptureOptions,
  ) => startSingleFlight(startPromiseRef, async () => {
    if (contextRef.current) return;

    const generation = ++captureGenerationRef.current;
    onLevelRef.current = onLevel || null;
    onSystemAudioStateChangeRef.current = options?.onSystemAudioStateChange || null;

    try {
      const micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          ...MIC_ONLY_AUDIO_CONSTRAINTS,
          echoCancellation: options?.systemAudio ?? false,
          noiseSuppression: options?.systemAudio ?? false,
        },
      });
      if (generation !== captureGenerationRef.current) {
        micStream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamsRef.current.push(micStream);

      let displayStream: MediaStream | null = null;
      if (options?.systemAudio) {
        try {
          const candidate = await navigator.mediaDevices.getDisplayMedia({
            audio: true,
            video: true,
          });
          candidate.getVideoTracks().forEach((track) => track.stop());
          if (generation !== captureGenerationRef.current) {
            candidate.getTracks().forEach((track) => track.stop());
            return;
          }
          if (candidate.getAudioTracks().length > 0) {
            displayStream = candidate;
            streamsRef.current.push(candidate);
            const handleEnded = () => {
              if (
                generation === captureGenerationRef.current
                && candidate.getAudioTracks().every((track) => track.readyState === "ended")
              ) {
                setSystemAudioActive(false);
                onSystemAudioStateChangeRef.current?.(false);
              }
            };
            candidate.getAudioTracks().forEach((track) => {
              track.addEventListener("ended", handleEnded, { once: true });
            });
          }
        } catch (err) {
          if (generation !== captureGenerationRef.current) return;
          // A declined or unavailable share falls back to mic-only capture.
          console.warn("System audio capture unavailable:", err);
        }
      }
      if (generation !== captureGenerationRef.current) return;

      const ctx = new AudioContext({ sampleRate: 16000 });
      contextRef.current = ctx;
      workletReadyRef.current = false;

      await attachPipeline(ctx, micStream, 0, onChunk);
      if (displayStream) {
        await attachPipeline(ctx, displayStream, 1, onChunk);
      }
      if (generation !== captureGenerationRef.current) return;
      const systemActive = Boolean(
        displayStream?.getAudioTracks().some((track) => track.readyState === "live")
      );
      setSystemAudioActive(systemActive);
      onSystemAudioStateChangeRef.current?.(systemActive);

      const levelBuf = new Uint8Array(128);
      const updateLevel = () => {
        let micRms = 0;
        let sysRms = 0;
        for (const { analyser, track } of analysersRef.current) {
          analyser.getByteTimeDomainData(levelBuf);
          let sum = 0;
          for (let i = 0; i < levelBuf.length; i++) {
            const v = (levelBuf[i] - 128) / 128;
            sum += v * v;
          }
          const rms = Math.sqrt(sum / levelBuf.length);
          if (track === 0) micRms = rms; else sysRms = rms;
        }
        onLevelRef.current?.(micRms);
        setAudioLevel(Math.min(1, micRms * 10));
        setSystemAudioLevel(Math.min(1, sysRms * 10));
        levelFrameRef.current = requestAnimationFrame(updateLevel);
      };
      levelFrameRef.current = requestAnimationFrame(updateLevel);

      setIsCapturing(true);
    } catch (err) {
      if (generation !== captureGenerationRef.current) return;
      releaseCapture();
      throw err;
    }
  }), [attachPipeline, releaseCapture]);

  const stopCapture = useCallback(() => {
    captureGenerationRef.current += 1;
    startPromiseRef.current = null;
    releaseCapture();
  }, [releaseCapture]);

  return { startCapture, stopCapture, isCapturing, audioLevel, systemAudioLevel, systemAudioActive };
}
