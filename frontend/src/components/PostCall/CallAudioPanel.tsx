import { useEffect, useState } from "react";
import type { CallSegment, ModelInfo, Session } from "../../types";
import * as api from "../../services/api";

interface CallAudioPanelProps {
  session: Session;
  segments: CallSegment[];
  onRetranscribed: () => Promise<void> | void;
}

export default function CallAudioPanel({ session, segments, onRetranscribed }: CallAudioPanelProps) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelId, setModelId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

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
    if (!window.confirm("Re-transcribing replaces the entire existing transcript for this session. Continue?")) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await api.retranscribeSession(session.id, modelId);
      setMessage(`Re-transcribed: ${res.entries} entries`);
      await onRetranscribed();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Re-transcription failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mb-4 rounded-xl bg-white p-4 shadow-sm">
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
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            disabled={busy}
            className="rounded border border-brand-light-gray-1 bg-white px-2 py-1.5 text-xs text-brand-dark-gray outline-none focus:border-brand-teal"
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
          <button
            onClick={handleRetranscribe}
            disabled={busy || !modelId}
            className="rounded bg-brand-teal px-3 py-1.5 font-body text-xs font-medium text-white transition-opacity disabled:opacity-40"
          >
            {busy ? "Re-transcribing..." : "Re-transcribe"}
          </button>
        </div>
      </div>
      {message && <p className="mt-2 font-body text-xs text-brand-mid-gray">{message}</p>}
    </div>
  );
}
