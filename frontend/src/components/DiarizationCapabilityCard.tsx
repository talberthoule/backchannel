import { useCallback, useEffect, useRef, useState } from "react";
import type { DiarizationBenchmarkResult, DiarizationDiagnostics } from "../types";
import * as api from "../services/api";
import { useConfirm } from "./ConfirmProvider";
import { MIC_ONLY_AUDIO_CONSTRAINTS } from "../hooks/useAudioCapture";

const RECORDING_MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
];
// Mirrors backend MIN/MAX_BENCHMARK_SECONDS: one 15s live Sortformer window
// plus 5s of slack, after which recording stops and validation runs.
const MIN_BENCHMARK_SECONDS = 15;
const MAX_RECORDING_SECONDS = MIN_BENCHMARK_SECONDS + 5;
const MAX_VOICE_RECORDING_SECONDS = 10;
type RecordingMode = "benchmark" | "voice";

export default function DiarizationCapabilityCard() {
  const [diarization, setDiarization] = useState<DiarizationDiagnostics | null>(null);
  const [benchmark, setBenchmark] = useState<DiarizationBenchmarkResult | null>(null);
  const [benchmarkFile, setBenchmarkFile] = useState<File | null>(null);
  const [benchmarking, setBenchmarking] = useState(false);
  const [recordingMode, setRecordingMode] = useState<RecordingMode | null>(null);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [voiceEnrolled, setVoiceEnrolled] = useState<boolean | null>(null);
  const [voiceSaving, setVoiceSaving] = useState(false);
  const [diagnosticError, setDiagnosticError] = useState<string | null>(null);
  const [loadingDiagnostics, setLoadingDiagnostics] = useState(true);
  const [savingSelection, setSavingSelection] = useState(false);
  const [savingThreshold, setSavingThreshold] = useState(false);
  const [thresholdDraft, setThresholdDraft] = useState(0.72);
  const [infoOpen, setInfoOpen] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<number | null>(null);
  const recordingGenerationRef = useRef(0);
  const { confirm } = useConfirm();

  const load = useCallback(async () => {
    setLoadingDiagnostics(true);
    try {
      const [result, voiceProfile] = await Promise.all([
        api.getDiarizationDiagnostics(),
        api.getVoiceProfileStatus(),
      ]);
      setDiarization(result);
      setVoiceEnrolled(voiceProfile.enrolled);
      setDiagnosticError(null);
    } catch (err) {
      console.error("Failed to load diarization diagnostics", err);
      setDiagnosticError("Unable to load diagnostics. The backend may still be starting.");
    } finally {
      setLoadingDiagnostics(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (diarization) {
      setThresholdDraft(diarization.speaker_similarity_threshold);
    }
  }, [diarization?.speaker_similarity_threshold]);

  useEffect(() => {
    if (!diagnosticError || diarization) {
      return;
    }

    const retry = window.setTimeout(() => {
      void load();
    }, 3000);

    return () => window.clearTimeout(retry);
  }, [diagnosticError, diarization, load]);

  const clearRecordingTimer = useCallback(() => {
    if (timerRef.current != null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const stopMediaTracks = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
  }, []);

  useEffect(() => () => {
    recordingGenerationRef.current += 1;
    const recorder = recorderRef.current;
    if (recorder) {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      if (recorder.state === "recording") recorder.stop();
    }
    clearRecordingTimer();
    stopMediaTracks();
  }, [clearRecordingTimer, stopMediaTracks]);

  const runBenchmark = async (file: File) => {
    setBenchmarking(true);
    setDiagnosticError(null);
    try {
      const result = await api.runSortformerBenchmark(file);
      setBenchmark(result);
      await load();
    } catch (err) {
      console.error("Benchmark failed", err);
      setDiagnosticError(err instanceof Error ? err.message : "Benchmark failed.");
    } finally {
      setBenchmarking(false);
    }
  };

  const handleUploadedBenchmark = () => {
    if (benchmarkFile) {
      void runBenchmark(benchmarkFile);
    }
  };

  const saveVoiceProfile = async (file: File) => {
    setVoiceSaving(true);
    setDiagnosticError(null);
    try {
      const result = await api.replaceVoiceProfile(file);
      setVoiceEnrolled(result.enrolled);
    } catch (err) {
      console.error("Voice enrollment failed", err);
      setDiagnosticError(err instanceof Error ? err.message : "Voice enrollment failed.");
    } finally {
      setVoiceSaving(false);
    }
  };

  const removeVoiceProfile = async () => {
    const ok = await confirm({
      title: "Delete voice profile",
      message: "Delete your saved voice profile?",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    setVoiceSaving(true);
    setDiagnosticError(null);
    try {
      await api.deleteVoiceProfile();
      setVoiceEnrolled(false);
    } catch (err) {
      console.error("Voice profile deletion failed", err);
      setDiagnosticError(err instanceof Error ? err.message : "Unable to delete voice profile.");
    } finally {
      setVoiceSaving(false);
    }
  };

  const startMicRecording = async (mode: RecordingMode) => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setDiagnosticError("Browser microphone recording is not available.");
      return;
    }

    const generation = recordingGenerationRef.current + 1;
    recordingGenerationRef.current = generation;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: mode === "voice" ? MIC_ONLY_AUDIO_CONSTRAINTS : true,
      });
      if (generation !== recordingGenerationRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const recorder = new MediaRecorder(stream, getRecorderOptions());
      streamRef.current = stream;
      recorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        if (generation !== recordingGenerationRef.current) return;
        const file = createRecordedFile(chunksRef.current, recorder.mimeType);
        stopMediaTracks();
        clearRecordingTimer();
        setRecordingMode(null);
        setRecordingSeconds(0);
        if (mode === "voice") {
          void saveVoiceProfile(file);
        } else {
          setBenchmarkFile(file);
          void runBenchmark(file);
        }
      };

      recorder.start();
      setRecordingMode(mode);
      setRecordingSeconds(0);
      timerRef.current = window.setInterval(() => {
        setRecordingSeconds((seconds) => {
          const next = seconds + 1;
          const limit = mode === "voice" ? MAX_VOICE_RECORDING_SECONDS : MAX_RECORDING_SECONDS;
          if (next >= limit && recorder.state === "recording") {
            recorder.stop();
          }
          return next;
        });
      }, 1000);
    } catch (err) {
      if (generation !== recordingGenerationRef.current) return;
      console.error("Microphone recording failed", err);
      setDiagnosticError(err instanceof Error ? err.message : "Unable to start microphone recording.");
      stopMediaTracks();
      clearRecordingTimer();
      setRecordingMode(null);
    }
  };

  const stopMicRecording = () => {
    const recorder = recorderRef.current;
    if (recorder?.state === "recording") {
      recorder.stop();
    }
  };

  const selectDiarizer = async (mode: "lightweight" | "sortformer") => {
    setSavingSelection(true);
    setDiagnosticError(null);
    try {
      const updated = await api.updateDiarizationConfig({ selected_live_diarizer: mode });
      setDiarization(updated);
      setBenchmark(null);
    } catch (err) {
      console.error("Diarization selection failed", err);
      setDiagnosticError(err instanceof Error ? err.message : "Unable to update diarization mode.");
    } finally {
      setSavingSelection(false);
    }
  };

  const saveThreshold = async () => {
    const next = Number(thresholdDraft.toFixed(2));
    setSavingThreshold(true);
    setDiagnosticError(null);
    try {
      const updated = await api.updateDiarizationConfig({ speaker_similarity_threshold: next });
      setDiarization(updated);
    } catch (err) {
      console.error("Speaker matching threshold update failed", err);
      setDiagnosticError(err instanceof Error ? err.message : "Unable to update speaker matching sensitivity.");
    } finally {
      setSavingThreshold(false);
    }
  };

  const selectedMode = diarization?.selected_live_diarizer ?? "lightweight";
  const effectiveMode = diarization?.effective_live_diarizer ?? selectedMode;
  const enhancedUnlocked = Boolean(diarization?.sortformer_selectable);
  const savedThreshold = diarization?.speaker_similarity_threshold ?? 0.72;
  const thresholdChanged = Math.abs(thresholdDraft - savedThreshold) >= 0.005;
  const recommendation = benchmark?.recommended_live_diarizer ?? (enhancedUnlocked ? "sortformer" : diarization?.recommended_live_diarizer) ?? "lightweight";
  const deviceLabel = diarization
    ? `${diarization.device.toUpperCase()}${diarization.gpu_name ? ` - ${diarization.gpu_name}` : ""}`
    : "Unknown";
  const gpuLabel = !diarization
    ? "Unknown"
    : diarization.gpu_backend === "rocm"
      ? "ROCm (AMD)"
      : diarization.gpu_backend === "cuda"
        ? "CUDA (NVIDIA)"
        : "None (CPU)";

  return (
    <div className="rounded-xl bg-surface p-5 shadow-sm">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="font-display text-base font-bold text-brand-dark-gray">Diarization Capability</h3>
          <p className="mt-1 font-body text-xs leading-relaxed text-brand-gray">
            Validate whether this machine can run NeMo Sortformer fast enough for live speaker attribution.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loadingDiagnostics}
          className="rounded border border-brand-light-gray-1 px-3 py-1.5 font-body text-xs text-brand-dark-gray transition-colors hover:border-brand-teal hover:text-brand-teal"
        >
          {loadingDiagnostics ? "Checking..." : "Refresh"}
        </button>
      </div>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-y border-brand-light-gray-1 py-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <div>
            <p className="font-body text-[10px] uppercase text-brand-mid-gray">Live diarizer</p>
            <p className="font-body text-xs text-brand-gray">
              Active for new live calls and audio imports: <span className="font-semibold capitalize text-brand-dark-gray">{effectiveMode}</span>
            </p>
          </div>
          <InfoPopover open={infoOpen} onOpenChange={setInfoOpen} />
        </div>

        <div className="inline-flex rounded-lg border border-brand-light-gray-1 bg-brand-light-gray-2/50 p-1">
          <DiarizerModeButton
            label="Fallback"
            active={selectedMode === "lightweight"}
            disabled={savingSelection}
            onClick={() => void selectDiarizer("lightweight")}
          />
          <DiarizerModeButton
            label="Enhanced"
            active={selectedMode === "sortformer"}
            disabled={!enhancedUnlocked || savingSelection}
            title={enhancedUnlocked ? "Use Sortformer" : "Run a passing benchmark to unlock enhanced mode"}
            onClick={() => void selectDiarizer("sortformer")}
          />
        </div>
      </div>

      <div className="mb-4 grid gap-3 md:grid-cols-4">
        <Metric label="Recommendation" value={recommendation} capitalize />
        <Metric label="Device" value={deviceLabel} title={deviceLabel} />
        <Metric label="GPU accel" value={gpuLabel} />
        <Metric
          label="RTF"
          value={
            benchmark?.real_time_factor != null
              ? benchmark.real_time_factor.toFixed(2)
              : diarization?.benchmark_real_time_factor != null
                ? diarization.benchmark_real_time_factor.toFixed(2)
                : "Not run"
          }
        />
      </div>

      <div className="mb-4 rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="font-body text-[10px] uppercase text-brand-mid-gray">Speaker matching</p>
            <p className="font-body text-xs text-brand-gray">
              Match threshold: <span className="font-semibold text-brand-dark-gray">{thresholdDraft.toFixed(2)}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={() => void saveThreshold()}
            disabled={!thresholdChanged || savingThreshold || loadingDiagnostics}
            className="rounded bg-brand-teal px-3 py-1.5 font-body text-xs font-medium text-white transition-colors hover:bg-brand-teal-dark disabled:cursor-not-allowed disabled:bg-brand-light-gray-1"
          >
            {savingThreshold ? "Saving..." : "Apply"}
          </button>
        </div>
        <div className="flex items-center gap-3">
          <span className="font-body text-[10px] text-brand-mid-gray">Merge more</span>
          <input
            type="range"
            min={0.5}
            max={0.95}
            step={0.01}
            value={thresholdDraft}
            onChange={(e) => setThresholdDraft(Number(e.target.value))}
            className="min-w-0 flex-1 accent-brand-teal"
          />
          <span className="font-body text-[10px] text-brand-mid-gray">Split more</span>
          <input
            type="number"
            min={0.5}
            max={0.95}
            step={0.01}
            value={thresholdDraft.toFixed(2)}
            onChange={(e) => {
              const value = Number(e.target.value);
              if (!Number.isNaN(value)) {
                setThresholdDraft(Math.min(0.95, Math.max(0.5, value)));
              }
            }}
            className="w-20 rounded border border-brand-light-gray-1 bg-surface px-2 py-1 font-body text-xs text-brand-dark-gray"
          />
        </div>
      </div>

      <div className="mb-4 rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="font-body text-[10px] uppercase text-brand-mid-gray">My voice profile</p>
            <p className="mt-1 font-body text-xs text-brand-gray">
              {voiceEnrolled
                ? "Your encrypted voice signature is ready for mic-only speaker matching."
                : "Record 4-10 seconds of your voice. Calibration audio is discarded; only its encrypted voice signature is kept."}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={recordingMode === "voice"
                ? stopMicRecording
                : () => void startMicRecording("voice")}
              disabled={
                voiceSaving
                || benchmarking
                || (recordingMode !== null && recordingMode !== "voice")
              }
              className="rounded border border-brand-teal px-3 py-1.5 font-body text-xs font-medium text-brand-teal transition-colors hover:bg-brand-teal hover:text-white disabled:cursor-not-allowed disabled:border-brand-light-gray-1 disabled:text-brand-mid-gray"
            >
              {recordingMode === "voice"
                ? `Stop (${recordingSeconds}s)`
                : voiceSaving
                  ? "Saving..."
                  : voiceEnrolled
                    ? "Replace Voice Profile"
                    : "Record Voice Profile"}
            </button>
            {voiceEnrolled && (
              <button
                type="button"
                onClick={() => void removeVoiceProfile()}
                disabled={voiceSaving || recordingMode !== null}
                className="rounded border border-brand-light-gray-1 px-3 py-1.5 font-body text-xs text-brand-gray transition-colors hover:border-red-300 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Delete
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="mb-4 rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-2">
        <p className="font-body text-xs text-brand-gray">
          {loadingDiagnostics
            ? "Checking diarization capability..."
            : benchmark?.reason ?? diarization?.selection_reason ?? diarization?.reason ?? "Diagnostics have not been loaded."}
        </p>
        {diarization?.gpu_memory_gb != null && (
          <p className="mt-1 font-body text-[10px] text-brand-mid-gray">GPU memory: {diarization.gpu_memory_gb} GB</p>
        )}
        <p className="mt-1 font-mono text-[10px] text-brand-mid-gray">{diarization?.model_id}</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <input
          type="file"
          accept=".m4a,.mp3,.wav,.ogg,.flac,.webm,audio/*"
          onChange={(e) => setBenchmarkFile(e.target.files?.[0] ?? null)}
          className="max-w-sm rounded border border-brand-light-gray-1 bg-surface px-3 py-1.5 font-body text-xs text-brand-dark-gray"
        />
        <button
          onClick={handleUploadedBenchmark}
          disabled={!benchmarkFile || benchmarking || recordingMode !== null}
          className="rounded bg-brand-teal px-3 py-1.5 font-body text-xs font-medium text-white transition-colors hover:bg-brand-teal-dark disabled:cursor-not-allowed disabled:bg-brand-light-gray-1"
        >
          {benchmarking ? "Benchmarking..." : "Run Benchmark"}
        </button>
        <button
          onClick={recordingMode === "benchmark"
            ? stopMicRecording
            : () => void startMicRecording("benchmark")}
          disabled={
            voiceSaving
            || (benchmarking && recordingMode !== "benchmark")
            || (recordingMode !== null && recordingMode !== "benchmark")
          }
          className="rounded border border-brand-teal px-3 py-1.5 font-body text-xs font-medium text-brand-teal transition-colors hover:bg-brand-teal hover:text-white disabled:cursor-not-allowed disabled:border-brand-light-gray-1 disabled:text-brand-mid-gray"
        >
          {recordingMode === "benchmark"
            ? `Stop Recording (${recordingSeconds}s)`
            : "Record Mic Benchmark"}
        </button>
        {benchmark ? (
          <span className="font-body text-xs text-brand-mid-gray">
            {benchmark.audio_seconds.toFixed(1)}s benchmarked in {benchmark.processing_seconds.toFixed(1)}s processing
          </span>
        ) : benchmarkFile && (
          <span className="font-body text-[10px] text-brand-mid-gray">
            Needs at least {MIN_BENCHMARK_SECONDS}s of audio; only the first {MAX_RECORDING_SECONDS}s is benchmarked.
          </span>
        )}
      </div>

      {diagnosticError && (
        <p className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 font-body text-xs text-red-700">
          {diagnosticError} {loadingDiagnostics ? "Retrying..." : ""}
        </p>
      )}
    </div>
  );
}

function DiarizerModeButton({
  label,
  active,
  disabled,
  title,
  onClick,
}: {
  label: string;
  active: boolean;
  disabled?: boolean;
  title?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`rounded-md px-3 py-1.5 font-body text-xs font-semibold transition-all active:translate-y-px disabled:cursor-not-allowed disabled:opacity-45 ${
        active
          ? "bg-surface text-brand-teal shadow-sm"
          : "text-brand-mid-gray hover:bg-surface/70 hover:text-brand-dark-gray"
      }`}
    >
      {label}
    </button>
  );
}

function InfoPopover({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <div
      className="relative"
      onMouseEnter={() => onOpenChange(true)}
      onMouseLeave={() => onOpenChange(false)}
    >
      <button
        type="button"
        aria-label="Compare diarization modes"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
        className="grid h-6 w-6 place-items-center rounded-full border border-brand-light-gray-1 bg-surface font-display text-[11px] font-bold text-brand-teal shadow-sm transition-colors hover:border-brand-teal"
      >
        i
      </button>
      {open && (
        <div className="absolute left-0 top-8 z-20 w-[min(22rem,calc(100vw-3rem))] rounded-lg border border-brand-light-gray-1 bg-surface p-4 shadow-xl shadow-brand-dark-gray/10">
          <div className="space-y-3 font-body text-xs leading-relaxed text-brand-gray">
            <p>
              <span className="font-semibold text-brand-dark-gray">Fallback</span> uses the local VAD and speaker-embedding path. It streams quickly, runs on CPU, and is the safer default when hardware or model availability changes.
            </p>
            <p>
              <span className="font-semibold text-brand-dark-gray">Enhanced</span> uses NeMo Sortformer after this machine passes the benchmark. It can separate speaker turns more accurately in multi-speaker calls, but it is heavier and processes audio in short batches.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, title, capitalize = false }: { label: string; value: string; title?: string; capitalize?: boolean }) {
  return (
    <div className="rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 p-3">
      <p className="font-body text-[10px] uppercase text-brand-mid-gray">{label}</p>
      <p
        className={`mt-1 truncate font-display text-sm font-bold text-brand-dark-gray ${capitalize ? "capitalize" : ""}`}
        title={title ?? value}
      >
        {value}
      </p>
    </div>
  );
}

function getRecorderOptions(): MediaRecorderOptions {
  const mimeType = RECORDING_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
  return mimeType ? { mimeType } : {};
}

function createRecordedFile(chunks: BlobPart[], mimeType: string): File {
  const type = mimeType || "audio/webm";
  const extension = type.includes("mp4") ? "m4a" : "webm";
  return new File([new Blob(chunks, { type })], `mic-benchmark.${extension}`, { type });
}
