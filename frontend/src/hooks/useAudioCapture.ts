import { useCallback, useRef, useState } from "react";

export type AudioTrack = 0 | 1; // 0 = mic, 1 = system audio

interface CaptureOptions {
  systemAudio?: boolean;
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
  const workletReadyRef = useRef(false);

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

  const startCapture = useCallback(async (
    onChunk: (chunk: ArrayBuffer, track: AudioTrack) => void,
    onLevel?: (level: number) => void,
    options?: CaptureOptions,
  ) => {
    onLevelRef.current = onLevel || null;
    const micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: true,
      },
    });
    streamsRef.current.push(micStream);

    const ctx = new AudioContext({ sampleRate: 16000 });
    contextRef.current = ctx;
    workletReadyRef.current = false;

    await attachPipeline(ctx, micStream, 0, onChunk);

    if (options?.systemAudio) {
      try {
        // Chrome requires requesting video with display capture; we drop it.
        const displayStream = await navigator.mediaDevices.getDisplayMedia({
          audio: true,
          video: true,
        });
        displayStream.getVideoTracks().forEach((t) => t.stop());
        if (displayStream.getAudioTracks().length > 0) {
          streamsRef.current.push(displayStream);
          await attachPipeline(ctx, displayStream, 1, onChunk);
          setSystemAudioActive(true);
        }
      } catch (err) {
        // User declined the share prompt or no tab audio — mic-only is fine.
        console.warn("System audio capture unavailable:", err);
      }
    }

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
      setAudioLevel(Math.min(1, micRms * 3)); // scale up for visibility
      setSystemAudioLevel(Math.min(1, sysRms * 3));
      levelFrameRef.current = requestAnimationFrame(updateLevel);
    };
    levelFrameRef.current = requestAnimationFrame(updateLevel);

    setIsCapturing(true);
  }, [attachPipeline]);

  const stopCapture = useCallback(() => {
    cancelAnimationFrame(levelFrameRef.current);
    setAudioLevel(0);
    setSystemAudioLevel(0);
    setSystemAudioActive(false);
    onLevelRef.current = null;

    for (const node of nodesRef.current) {
      node.disconnect();
    }
    nodesRef.current = [];
    analysersRef.current = [];

    if (contextRef.current) {
      contextRef.current.close();
      contextRef.current = null;
    }
    for (const stream of streamsRef.current) {
      stream.getTracks().forEach((t) => t.stop());
    }
    streamsRef.current = [];

    setIsCapturing(false);
  }, []);

  return { startCapture, stopCapture, isCapturing, audioLevel, systemAudioLevel, systemAudioActive };
}
