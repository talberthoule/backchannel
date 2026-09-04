import { useEffect, useState } from "react";
import type { CallSegment, ModelInfo, Session, TranscriptionJob } from "../../types";
import * as api from "../../services/api";
import { groupModels, optionLabel } from "../../lib/modelOptions";
import { useConfirm } from "../ConfirmProvider";
import TranscriptionJobProgress from "../TranscriptionJobProgress";

interface CallAudioPanelProps {
  session: Session;
  segments: CallSegment[];
  onRetranscribed: () => Promise<void> | void;
}

export default function CallAudioPanel({ session, segments, onRetranscribed }: CallAudioPanelProps) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelId, setModelId] = useState("");
  const [job, setJob] = useState<TranscriptionJob | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const { confirm } = useConfirm();
  const busy = job ? api.transcriptionJobActive(job) : false;

  const audioSegments = segments.filter((s) => s.audio_path);

  useEffect(() => {
    api.listModels().then((all) => {
      const batch = all.filter((m) => m.supports_batch_audio && m.key_available !== false);
      setModels(batch);
      if (batch.length > 0) setModelId(batch[0].id);
    }).catch(() => {});
  }, []);

  if (audioSegments.length === 0) return null;

  const handleRetranscribe = async () => {
    if (!modelId) return;
    const ok = await confirm({
      title: "Re-transcribe call audio",
      message: "The existing transcript stays in place until the replacement finishes.",
      confirmLabel: "Re-transcribe",
      tone: "danger",
    });
    if (!ok) return;
    setMessage(null);
    try {
      const queued = await api.retranscribeSession(session.id, modelId);
      setJob(queued);
      const result = await api.waitForTranscriptionJob(session.id, queued, setJob);
      if (result.status === "completed") {
        setMessage(`Re-transcribed ${result.entries} entries.`);
        await onRetranscribed();
      } else if (result.status === "canceled") {
        setMessage("Re-transcription canceled. The existing transcript was kept.");
      } else {
        setMessage(result.error || "Re-transcription failed.");
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Re-transcription failed");
    }
  };

  const handleCancel = async () => {
    try {
      setJob(await api.cancelTranscriptionJob(session.id, "retranscription"));
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not cancel re-transcription.");
    }
  };

  return (
    <div className="mb-4 rounded-xl bg-surface p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          {audioSegments.map((seg) => (
            <div key={seg.id} className="flex items-center gap-2">
              <span className="font-body text-xs text-brand-mid-gray">Call {seg.segment_number}</span>
              <audio controls preload="none" src={api.segmentAudioUrl(session.id, seg.segment_number)} className="h-8" />
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <select
            aria-label="Transcription model"
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            disabled={busy}
            className="rounded border border-brand-light-gray-1 bg-surface px-2 py-1.5 text-xs text-brand-dark-gray focus:border-brand-teal"
          >
            {groupModels(models).map((group) => (
              <optgroup key={group.provider} label={group.provider}>
                {group.models.map((m) => (
                  <option key={m.id} value={m.id}>{optionLabel(m)}</option>
                ))}
              </optgroup>
            ))}
          </select>
          <button
            type="button"
            onClick={handleRetranscribe}
            disabled={busy || !modelId}
            className="min-h-11 rounded bg-brand-teal px-3 font-body text-xs font-medium text-white transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal focus-visible:ring-offset-2 disabled:opacity-40"
          >
            Re-transcribe
          </button>
        </div>
      </div>
      {job && api.transcriptionJobActive(job) && (
        <TranscriptionJobProgress job={job} onCancel={handleCancel} />
      )}
      {message && <p role="status" className="mt-2 font-body text-xs text-brand-mid-gray">{message}</p>}
    </div>
  );
}
