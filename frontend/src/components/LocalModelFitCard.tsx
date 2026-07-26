import { useCallback, useEffect, useState } from "react";
import type { FitRole, FitVerdict, LocalFitReport, LocalFitSummary, TextModelFit } from "../types";
import * as api from "../services/api";

// Mirrors backend app/services/local_fit.py HEADROOM: a call should finish
// within half its interval. Used only to keep verdicts truthful after applying
// new intervals without re-benchmarking.
const HEADROOM = 0.5;

function verdictFor(latencySeconds: number, budgetSeconds: number): FitVerdict {
  if (latencySeconds <= 0) return "green";
  if (budgetSeconds <= 0) return "red";
  const ratio = latencySeconds / budgetSeconds;
  if (ratio <= HEADROOM) return "green";
  if (ratio <= 1) return "yellow";
  return "red";
}

const VERDICT_STYLE: Record<FitVerdict, string> = {
  green: "border-emerald-200 bg-emerald-50 text-emerald-700",
  yellow: "border-amber-200 bg-amber-50 text-amber-800",
  red: "border-red-200 bg-red-50 text-red-700",
};

const VERDICT_LABEL: Record<FitVerdict, string> = {
  green: "Keeps up",
  yellow: "Tight",
  red: "Too slow",
};

interface LocalModelFitCardProps {
  /** Called after intervals are applied so the Agents tab reflects the change. */
  onIntervalsApplied?: () => void;
}

export default function LocalModelFitCard({ onIntervalsApplied }: LocalModelFitCardProps) {
  const [summary, setSummary] = useState<LocalFitSummary | null>(null);
  const [report, setReport] = useState<LocalFitReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [applyingModel, setApplyingModel] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    try {
      setSummary(await api.getLocalFitSummary());
      setError(null);
    } catch (err) {
      console.error("Failed to load local fit summary", err);
      setError("Unable to load local models. The backend may still be starting.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadSummary(); }, [loadSummary]);

  const runTest = async () => {
    setRunning(true);
    setError(null);
    setNotice(null);
    try {
      setReport(await api.runLocalFit());
    } catch (err) {
      console.error("Local fit test failed", err);
      setError(err instanceof Error ? err.message : "Fit test failed.");
    } finally {
      setRunning(false);
    }
  };

  const applyIntervals = async (model: TextModelFit) => {
    const updates = model.roles
      .filter((role) => role.changed)
      .map((role) => ({ slug: role.slug, interval_seconds: role.recommended_interval_seconds }));
    if (updates.length === 0) return;
    setApplyingModel(model.model_id);
    setError(null);
    setNotice(null);
    try {
      const { applied } = await api.applyLocalFitIntervals(updates);
      // Reflect the new budgets in the shown report without re-benchmarking.
      setReport((prev) => (prev ? applyToReport(prev, applied) : prev));
      setNotice(`Applied ${Object.keys(applied).length} interval change(s) for ${model.model_name}.`);
      await loadSummary();
      onIntervalsApplied?.();
    } catch (err) {
      console.error("Applying intervals failed", err);
      setError(err instanceof Error ? err.message : "Unable to apply intervals.");
    } finally {
      setApplyingModel(null);
    }
  };

  const hasModels = summary?.has_local_text_models ?? false;

  return (
    <div className="rounded-xl bg-surface p-5 shadow-sm">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="font-display text-base font-bold text-brand-dark-gray">Local Model Fit Test</h3>
          <p className="mt-1 max-w-2xl font-body text-xs leading-relaxed text-brand-gray">
            Times a role-sized analysis call on each self-hosted text model and checks whether it keeps
            up with every live agent&apos;s cycle. This measures keep-up speed only, not answer quality.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadSummary}
            disabled={loading || running}
            className="rounded border border-brand-light-gray-1 px-3 py-1.5 font-body text-xs text-brand-dark-gray transition-colors hover:border-brand-teal hover:text-brand-teal disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Checking..." : "Refresh"}
          </button>
          <button
            onClick={runTest}
            disabled={!hasModels || running || loading}
            className="rounded bg-brand-teal px-3 py-1.5 font-body text-xs font-medium text-white transition-colors hover:bg-brand-teal-dark disabled:cursor-not-allowed disabled:bg-brand-light-gray-1"
          >
            {running ? "Running..." : report ? "Re-run test" : "Run fit test"}
          </button>
        </div>
      </div>

      {!loading && !hasModels && (
        <div className="rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-3">
          <p className="font-body text-xs leading-relaxed text-brand-gray">
            No self-hosted text models found. Add an on-prem OpenAI-compatible endpoint (Ollama, LM Studio,
            vLLM, LiteLLM) under <span className="font-semibold text-brand-dark-gray">API Keys</span>, then
            run this test to see whether it can drive the live analysis agents offline.
          </p>
        </div>
      )}

      {hasModels && summary && !report && !running && (
        <div className="rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-3">
          <p className="font-body text-xs text-brand-gray">
            Ready to test {summary.models.length} self-hosted text model{summary.models.length === 1 ? "" : "s"}:
            {" "}
            <span className="text-brand-dark-gray">{summary.models.map((m) => m.name).join(", ")}</span>.
            The test makes a few short calls per model, so it takes a moment.
          </p>
        </div>
      )}

      {running && (
        <div className="rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-3">
          <p className="font-body text-xs text-brand-gray">
            Running the fit test... timing a short-window and a long-window call on each model.
          </p>
        </div>
      )}

      {report && !running && (
        <div className="space-y-4">
          {report.text_models.map((model) => (
            <ModelFitBlock
              key={model.model_id}
              model={model}
              applying={applyingModel === model.model_id}
              onApply={() => void applyIntervals(model)}
            />
          ))}
        </div>
      )}

      {notice && (
        <p className="mt-3 rounded border border-emerald-200 bg-emerald-50 px-3 py-2 font-body text-xs text-emerald-800">
          {notice}
        </p>
      )}
      {error && (
        <p className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 font-body text-xs text-red-700">
          {error}
        </p>
      )}

      <div className="mt-4 rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-2">
        <p className="font-body text-xs leading-relaxed text-brand-gray">
          To actually run an agent on a local model, also select it on the Agents tab. Local transcription
          (speech-to-text) speed is measured separately on the Diarization Capability card below.
        </p>
      </div>
    </div>
  );
}

function ModelFitBlock({
  model,
  applying,
  onApply,
}: {
  model: TextModelFit;
  applying: boolean;
  onApply: () => void;
}) {
  const changes = model.roles.filter((role) => role.changed).length;

  return (
    <div className="rounded-lg border border-brand-light-gray-1 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-display text-sm font-bold text-brand-dark-gray" title={model.model_id}>
            {model.model_name}
          </p>
          {model.status === "ok" && model.short && model.long ? (
            <p className="mt-0.5 font-body text-[11px] text-brand-mid-gray">
              Short window {model.short.latency_seconds.toFixed(1)}s - Long window {model.long.latency_seconds.toFixed(1)}s per call
            </p>
          ) : (
            <p className="mt-0.5 font-body text-[11px] text-red-700">{model.reason || "Benchmark failed."}</p>
          )}
        </div>
        {model.status === "ok" && changes > 0 && (
          <button
            onClick={onApply}
            disabled={applying}
            className="rounded bg-brand-teal px-3 py-1.5 font-body text-xs font-medium text-white transition-colors hover:bg-brand-teal-dark disabled:cursor-not-allowed disabled:bg-brand-light-gray-1"
          >
            {applying ? "Applying..." : `Apply recommended intervals (${changes})`}
          </button>
        )}
      </div>

      {model.status === "ok" && model.roles.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse font-body text-xs">
            <thead>
              <tr className="text-left text-brand-mid-gray">
                <th className="py-1 pr-3 font-medium">Agent</th>
                <th className="py-1 pr-3 font-medium">Window</th>
                <th className="py-1 pr-3 font-medium">Call time</th>
                <th className="py-1 pr-3 font-medium">Cycle budget</th>
                <th className="py-1 pr-3 font-medium">Verdict</th>
                <th className="py-1 font-medium">Recommended</th>
              </tr>
            </thead>
            <tbody>
              {model.roles.map((role) => (
                <RoleRow key={role.slug} role={role} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RoleRow({ role }: { role: FitRole }) {
  return (
    <tr className="border-t border-brand-light-gray-1">
      <td className="py-1.5 pr-3 text-brand-dark-gray">{role.name}</td>
      <td className="py-1.5 pr-3 capitalize text-brand-gray">{role.prompt_profile}</td>
      <td className="py-1.5 pr-3 text-brand-gray">{role.latency_seconds.toFixed(1)}s</td>
      <td className="py-1.5 pr-3 text-brand-gray">{role.budget_seconds}s</td>
      <td className="py-1.5 pr-3">
        <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold ${VERDICT_STYLE[role.verdict]}`}>
          {VERDICT_LABEL[role.verdict]}
        </span>
      </td>
      <td className="py-1.5 text-brand-gray">
        {role.changed ? (
          <span className="font-semibold text-brand-teal">{role.recommended_interval_seconds}s</span>
        ) : (
          <span className="text-brand-mid-gray">{role.budget_seconds}s (no change)</span>
        )}
      </td>
    </tr>
  );
}

/** Fold applied intervals back into the report so verdicts stay truthful. */
function applyToReport(report: LocalFitReport, applied: Record<string, number>): LocalFitReport {
  const text_models = report.text_models.map((model) => ({
    ...model,
    roles: model.roles.map((role) => {
      const budget = applied[role.slug];
      if (budget == null) return role;
      return {
        ...role,
        budget_seconds: budget,
        verdict: verdictFor(role.latency_seconds, budget),
        recommended_interval_seconds: budget,
        changed: false,
      };
    }),
  }));
  return { ...report, intervals: { ...report.intervals, ...applied }, text_models };
}
