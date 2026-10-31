import type { TranscriptionJob } from "../types";
import { useTranslation } from "react-i18next";
import "../i18n";

interface Props {
  job: TranscriptionJob;
  onCancel: () => void;
}

export default function TranscriptionJobProgress({ job, onCancel }: Props) {
  const { t } = useTranslation();
  const action = job.kind === "audio_import"
    ? t("transcriptionJob.transcribing", { file: job.filename || "audio" })
    : t("transcriptionJob.retranscribing");
  const recordingLabel = t("transcriptionJob.recording", { count: job.total_segments });
  const entryLabel = t("transcriptionJob.entry", { count: job.entries });

  return (
    <div role="status" aria-live="polite" className="mt-3 border-t border-brand-light-gray-1 pt-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-body text-sm font-medium text-brand-dark-gray">
            {action} {t("transcriptionJob.withModel", { model: job.model_id })}
          </p>
          <p className="mt-1 font-body text-xs text-brand-mid-gray">
            {t("transcriptionJob.progress", {
              done: job.segments_done,
              total: job.total_segments,
              recordings: recordingLabel,
              entries: job.entries,
              entryLabel,
            })}
          </p>
        </div>
        <button
          type="button"
          onClick={onCancel}
          disabled={job.status === "canceling"}
          className="min-h-11 rounded border border-brand-light-gray-1 px-3 font-body text-xs font-medium text-brand-dark-gray transition-colors hover:border-brand-mid-gray focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal disabled:cursor-not-allowed disabled:opacity-50"
        >
          {job.status === "canceling" ? t("transcriptionJob.canceling") : t("common.cancel")}
        </button>
      </div>
      <progress
        value={job.progress}
        max={100}
        aria-label={t("transcriptionJob.progressAria", { action })}
        className="mt-2 h-1.5 w-full overflow-hidden rounded-full [&::-webkit-progress-bar]:bg-brand-light-gray-1 [&::-webkit-progress-value]:bg-brand-teal [&::-moz-progress-bar]:bg-brand-teal"
      />
    </div>
  );
}
