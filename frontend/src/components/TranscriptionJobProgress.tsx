import type { TranscriptionJob } from "../types";

interface Props {
  job: TranscriptionJob;
  onCancel: () => void;
}

export default function TranscriptionJobProgress({ job, onCancel }: Props) {
  const action = job.kind === "audio_import"
    ? `Transcribing ${job.filename || "audio"}`
    : "Re-transcribing";
  const recordingLabel = job.total_segments === 1 ? "recording" : "recordings";
  const entryLabel = job.entries === 1 ? "entry" : "entries";

  return (
    <div role="status" aria-live="polite" className="mt-3 border-t border-brand-light-gray-1 pt-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-body text-sm font-medium text-brand-dark-gray">
            {action} with <span className="font-mono text-xs">{job.model_id}</span>
          </p>
          <p className="mt-1 font-body text-xs text-brand-mid-gray">
            {job.segments_done} of {job.total_segments} {recordingLabel} · {job.entries} transcript {entryLabel}
          </p>
        </div>
        <button
          type="button"
          onClick={onCancel}
          disabled={job.status === "canceling"}
          className="min-h-11 rounded border border-brand-light-gray-1 px-3 font-body text-xs font-medium text-brand-dark-gray transition-colors hover:border-brand-mid-gray focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal disabled:cursor-not-allowed disabled:opacity-50"
        >
          {job.status === "canceling" ? "Canceling…" : "Cancel"}
        </button>
      </div>
      <progress
        value={job.progress}
        max={100}
        aria-label={`${action} progress`}
        className="mt-2 h-1.5 w-full overflow-hidden rounded-full [&::-webkit-progress-bar]:bg-brand-light-gray-1 [&::-webkit-progress-value]:bg-brand-teal [&::-moz-progress-bar]:bg-brand-teal"
      />
    </div>
  );
}
