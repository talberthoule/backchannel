import { useCallback, useEffect, useRef, useState } from "react";

export type AudioTrack = 0 | 1; // 0 = mic, 1 = system audio

/**
 * A live 0-1 audio level read imperatively. Meter values change at frame rate,
 * so they are kept out of React state entirely: consumers read `current` inside
 * their own animation frame and paint the DOM directly (ALP-291).
 */
export interface AudioLevelSource {
  readonly current: number;
}

/** Stable empty source for an indicator that has no live capture behind it. */
export const SILENT_AUDIO_LEVEL: AudioLevelSource = { current: 0 };

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

interface SystemCaptureHandle {
  /** Silences the track-1 pipeline so no further frames reach onChunk. */
  disconnect: () => void;
  /** The display stream, whose tracks are released. */
  stream: { getTracks(): { stop(): void }[] } | null;
  /** Reports the new system-track state to the backend. */
  notify: ((active: boolean) => void) | null;
}

/**
 * Builds the one function that ends system capture, whatever triggered it.
 *
 * Chrome's own "Stop sharing" bar is the only way to end a share mid-call, and
 * it ends the track without any in-page click to hang logic off. Ending must
 * therefore do the whole job from a track event: stop forwarding frames, release
 * the tracks, and tell the backend the system track went inactive so it closes
 * the split segment writer and diarizer state. Forgetting the first of those is
 * what let frames keep flowing in lockstep with the mic for a whole call.
 *
 * Idempotent, because the native bar, an explicit stop, and full capture
 * release can all reach it, and a second track_state would misreport the call.
 */
export function createSystemCaptureStop(handle: SystemCaptureHandle): () => boolean {
  let stopped = false;
  return () => {
    if (stopped) return false;
    stopped = true;
    handle.disconnect();
    handle.stream?.getTracks().forEach((track) => track.stop());
    handle.notify?.(false);
    return true;
  };
}

// Samples are written straight into a preallocated Int16Array: boxing every
// sample into a JS array and splicing it ran on the audio thread, where an
// overrun is a dropped render quantum.
//
// Do not fold the emit back into a single check after the loop. The chunk has
// to be flushed inline, every time it fills, or a render quantum larger than
// SAMPLES_NEEDED leaves a backlog that grows for the whole call: the previous
// one-emit-per-process() version emitted 30 chunks where this one emits 76
// over 30 blocks of 4096 samples. 128-sample quanta hide it; larger ones do
// not, and the two versions are byte-identical whenever it is hidden.
const WORKLET_CODE = `
  const SAMPLES_NEEDED = 1600; // ~100ms at 16kHz
  class PCM16Processor extends AudioWorkletProcessor {
    constructor() {
      super();
      this._chunk = new Int16Array(SAMPLES_NEEDED);
      this._filled = 0;
    }
    process(inputs) {
      const input = inputs[0];
      if (!input || !input[0]) return true;
      const float32 = input[0];
      for (let i = 0; i < float32.length; i++) {
        const s = Math.max(-1, Math.min(1, float32[i]));
        this._chunk[this._filled++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this._filled === SAMPLES_NEEDED) {
          const full = this._chunk;
          this._chunk = new Int16Array(SAMPLES_NEEDED);
          this._filled = 0;
          this.port.postMessage(full.buffer, [full.buffer]);
        }
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
  const [systemAudioActive, setSystemAudioActive] = useState(false);

  // Meter levels are refs, not state: they change ~60 times a second and the
  // only consumer is one meter's width, so publishing them through React would
  // re-render the whole app on every animation frame for the whole call.
  const audioLevelRef = useRef(0);
  const systemAudioLevelRef = useRef(0);
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
  const systemStopRef = useRef<(() => boolean) | null>(null);

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
    audioLevelRef.current = 0;
    systemAudioLevelRef.current = 0;
    setSystemAudioActive(false);
    onLevelRef.current = null;
    onSystemAudioStateChangeRef.current = null;
    systemStopRef.current = null;

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

  // Returns a teardown that silences just this track's pipeline. The system
  // side has to be able to stop on its own while the mic keeps running, which
  // a single whole-graph teardown cannot express.
  const attachPipeline = useCallback(async (
    ctx: AudioContext,
    stream: MediaStream,
    track: AudioTrack,
    onChunk: (chunk: ArrayBuffer, track: AudioTrack) => void,
  ): Promise<() => void> => {
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
      return () => teardown(workletNode, () => { workletNode.port.onmessage = null; });
    } catch {
      // Fallback: ScriptProcessorNode
      const scriptNode = ctx.createScriptProcessor(4096, 1, 1);
      const samplesPerChunk = 1600; // ~100ms at 16kHz
      let chunk = new Int16Array(samplesPerChunk);
      let filled = 0;

      scriptNode.onaudioprocess = (e: AudioProcessingEvent) => {
        const float32 = e.inputBuffer.getChannelData(0);
        for (let i = 0; i < float32.length; i++) {
          const s = Math.max(-1, Math.min(1, float32[i]));
          chunk[filled++] = s < 0 ? s * 0x8000 : s * 0x7fff;
          if (filled === samplesPerChunk) {
            const full = chunk;
            chunk = new Int16Array(samplesPerChunk);
            filled = 0;
            onChunk(full.buffer, track);
          }
        }
      };

      source.connect(scriptNode);
      scriptNode.connect(silentSink);
      nodesRef.current.push(scriptNode);
      return () => teardown(scriptNode, () => { scriptNode.onaudioprocess = null; });
    }

    function teardown(node: AudioNode, detach: () => void) {
      // Detach the callback first: disconnecting stops new buffers arriving,
      // but a buffer already in flight must not reach onChunk either.
      detach();
      source.disconnect();
      analyser.disconnect();
      node.disconnect();
      silentSink.disconnect();
      nodesRef.current = nodesRef.current.filter((n) => n !== node);
      analysersRef.current = analysersRef.current.filter((a) => a.track !== track);
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
          // Disabled, not stopped. Chrome hangs the share's lifetime on the
          // video track, so stopping it here throws away the only reliable
          // signal that the user hit "Stop sharing" - and a track we stop
          // ourselves never fires "ended" per spec. Disabled costs black
          // frames and keeps that signal.
          candidate.getVideoTracks().forEach((track) => { track.enabled = false; });
          if (generation !== captureGenerationRef.current) {
            candidate.getTracks().forEach((track) => track.stop());
            return;
          }
          if (candidate.getAudioTracks().length > 0) {
            displayStream = candidate;
            streamsRef.current.push(candidate);
            const handleEnded = () => {
              if (generation !== captureGenerationRef.current) return;
              if (systemStopRef.current?.()) setSystemAudioActive(false);
            };
            // Every track, because which one carries the stop differs by
            // browser and by share type; whichever ends first is the answer.
            candidate.getTracks().forEach((track) => {
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
        const disconnect = await attachPipeline(ctx, displayStream, 1, onChunk);
        const stream = displayStream;
        systemStopRef.current = createSystemCaptureStop({
          disconnect,
          stream,
          notify: (active) => onSystemAudioStateChangeRef.current?.(active),
        });
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
        audioLevelRef.current = Math.min(1, micRms * 10);
        systemAudioLevelRef.current = Math.min(1, sysRms * 10);
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

  return {
    startCapture,
    stopCapture,
    isCapturing,
    // Read per frame by AudioIndicator; never render these through React.
    audioLevelRef: audioLevelRef as AudioLevelSource,
    systemAudioLevelRef: systemAudioLevelRef as AudioLevelSource,
    systemAudioActive,
  };
}
