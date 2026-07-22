import type { PostProcessingProgress as ProgressState } from "../../types";

interface PostProcessingProgressProps {
  progress: ProgressState;
}

const STEP_LABELS: Record<string, string> = {
  speaker_assignment: "Speaker assignments",
  final_insights: "Final insight pass",
  insight_reconciliation: "Insight reconciliation",
  opportunity_matching: "Offering matching",
  call_briefing: "Call briefing",
  saving_session: "Save session",
};

// Fallback for older backends that do not announce the pipeline steps.
const DEFAULT_STEP_IDS = [
  "speaker_assignment",
  "final_insights",
  "insight_reconciliation",
  "opportunity_matching",
  "saving_session",
];

// Static class names so Tailwind generates them.
const GRID_COLS: Record<number, string> = {
  1: "sm:grid-cols-1",
  2: "sm:grid-cols-2",
  3: "sm:grid-cols-3",
  4: "sm:grid-cols-4",
  5: "sm:grid-cols-5",
  6: "sm:grid-cols-6",
};

function clampProgress(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

function stepState(stepIndex: number, currentStep: number, active: boolean): "done" | "active" | "pending" {
  const stepNumber = stepIndex + 1;
  if (!active && currentStep >= stepNumber) return "done";
  if (currentStep > stepNumber) return "done";
  if (currentStep === stepNumber) return "active";
  return "pending";
}

function detailsText(details?: Record<string, unknown>): string | null {
  if (!details) return null;
  const insights = Number(details.insights_saved ?? 0);
  const synthOps = Number(details.synthesizer_ops ?? 0);
  const opportunityOps = Number(details.opportunity_ops ?? 0);
  const parts = [
    insights ? `${insights} insight${insights === 1 ? "" : "s"} saved` : null,
    synthOps ? `${synthOps} insight update${synthOps === 1 ? "" : "s"}` : null,
    opportunityOps ? `${opportunityOps} offering match${opportunityOps === 1 ? "" : "es"}` : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" | ") : null;
}

export default function PostProcessingProgress({ progress }: PostProcessingProgressProps) {
  const percent = clampProgress(progress.progress);
  const currentStep = Math.max(0, Math.min(progress.totalSteps, progress.currentStep));
  const summary = detailsText(progress.details);
  const stepIds = progress.steps && progress.steps.length > 0 ? progress.steps : DEFAULT_STEP_IDS;

  return (
    <section className="border-b border-brand-light-gray-1 bg-surface px-6 py-4">
      <div className="mx-auto max-w-5xl">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-brand-amber animate-pulse" />
              <h2 className="font-display text-sm font-semibold uppercase text-brand-dark-gray">
                Post-processing
              </h2>
            </div>
            <p className="mt-1 font-body text-sm text-brand-gray">{progress.message}</p>
            {summary && (
              <p className="mt-1 font-body text-xs text-brand-mid-gray">{summary}</p>
            )}
          </div>
          <div className="font-mono text-sm font-semibold tabular-nums text-brand-dark-gray">
            {Math.round(percent)}%
          </div>
        </div>

        <div className="mt-3 h-2 overflow-hidden rounded-full bg-brand-light-gray-2">
          <div
            className="h-full rounded-full bg-brand-teal transition-all duration-500 ease-out"
            style={{ width: `${percent}%` }}
          />
        </div>

        <div className={`mt-3 grid grid-cols-1 gap-2 ${GRID_COLS[stepIds.length] ?? "sm:grid-cols-5"}`}>
          {stepIds.map((stepId, index) => {
            const state = stepState(index, currentStep, progress.active);
            return (
              <div
                key={stepId}
                className={`flex items-center gap-2 rounded-md border px-2.5 py-2 ${
                  state === "active"
                    ? "border-brand-teal bg-brand-teal/5 text-brand-teal"
                    : state === "done"
                      ? "border-brand-teal-light/30 bg-brand-teal-light/5 text-brand-dark-gray"
                      : "border-brand-light-gray-1 bg-brand-light-gray-2/50 text-brand-mid-gray"
                }`}
              >
                <span
                  className={`h-2 w-2 rounded-full ${
                    state === "active"
                      ? "bg-brand-teal"
                      : state === "done"
                        ? "bg-brand-teal-light"
                        : "bg-brand-mid-gray"
                  }`}
                />
                <span className="min-w-0 truncate font-body text-xs font-medium">{STEP_LABELS[stepId] ?? stepId}</span>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
