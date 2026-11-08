import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
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
      title: t("callAudio.confirmTitle"),
      message: t("callAudio.confirmMessage"),
      confirmLabel: t("callAudio.retranscribe"),
      tone: "danger",
    });
    if (!ok) return;
    setMessage(null);
    try {
      const queued = await api.retranscribeSession(session.id, modelId);
      setJob(queued);
      const result = await api.waitForTranscriptionJob(session.id, queued, setJob);
      if (result.status === "completed") {
        setMessage(t("callAudio.completed", { count: result.entries }));
        await onRetranscribed();
      } else if (result.status === "canceled") {
        setMessage(t("callAudio.canceled"));
      } else {
        setMessage(result.error || t("callAudio.failed"));
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : t("callAudio.failed"));
    }
  };

  const handleCancel = async () => {
    try {
      setJob(await api.cancelTranscriptionJob(session.id, "retranscription"));
    } catch (err) {
      setMessage(err instanceof Error ? err.message : t("callAudio.cancelFailed"));
    }
  };

  return (
    <div className="mb-4 rounded-xl bg-surface p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          {audioSegments.map((seg) => (
            <div key={seg.id} className="flex items-center gap-2">
              <span className="font-body text-xs text-brand-mid-gray">{t("callAudio.callNumber", { number: seg.segment_number })}</span>
              <audio controls preload="none" src={api.segmentAudioUrl(session.id, seg.segment_number)} className="h-8" />
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <select
            aria-label={t("callAudio.model")}
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
            {t("callAudio.retranscribe")}
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
