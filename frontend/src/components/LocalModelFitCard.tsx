import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  AsrFitReport,
  AsrModelFit,
  FitFeasibility,
  FitRole,
  FitVerdict,
  LocalCapabilities,
  LocalFitReport,
  LocalFitSummary,
  TextModelFit,
} from "../types";
import * as api from "../services/api";
import { useClipRecorder } from "../hooks/useClipRecorder";

const MAX_ASR_RECORD_SECONDS = 15;

// --- Scoring mirror of backend app/services/local_fit.py --------------------
// The contention slider recomputes verdicts/recommendations live without
// re-benchmarking, so this math must match the backend. Keep the two in sync.
const HEADROOM = 0.5;
const MIN_INTERVAL = 5;
const MAX_INTERVAL = 180;
const ROUND_STEP = 5;
const MIN_CONTENTION = 1;
const MAX_CONTENTION = 3;
const DEFAULT_CONTENTION = 1.5;
const POST_CALL_GREEN = 60;
const POST_CALL_YELLOW = 180;
const ASR_GREEN_RTF = 0.5;
const ASR_YELLOW_RTF = 1.0;
const ASR_LIVE_FEASIBLE = 0.33;
const ASR_LIVE_MARGINAL = 0.66;

const clampContention = (c: number) => Math.min(Math.max(c, MIN_CONTENTION), MAX_CONTENTION);
const effective = (value: number, contention: number) => value * clampContention(contention);
const roundUp = (value: number, step = ROUND_STEP) => (value <= 0 ? step : Math.ceil(value / step) * step);

function classifyLatency(eff: number, budget: number): FitVerdict {
  if (eff <= 0) return "green";
  if (budget <= 0) return "red";
  const ratio = eff / budget;
  if (ratio <= HEADROOM) return "green";
  if (ratio <= 1) return "yellow";
  return "red";
}
function classifyPostCall(eff: number): FitVerdict {
  if (eff <= POST_CALL_GREEN) return "green";
  if (eff <= POST_CALL_YELLOW) return "yellow";
  return "red";
}
function recommendInterval(eff: number, budget: number): number {
  const needed = eff > 0 ? roundUp(eff / HEADROOM) : MIN_INTERVAL;
  return Math.min(Math.max(budget, needed, MIN_INTERVAL), MAX_INTERVAL);
}
function classifyRtf(eff: number): FitVerdict {
  if (eff <= ASR_GREEN_RTF) return "green";
  if (eff <= ASR_YELLOW_RTF) return "yellow";
  return "red";
}
function classifyFeasibility(eff: number): FitFeasibility {
  if (eff <= ASR_LIVE_FEASIBLE) return "feasible";
  if (eff <= ASR_LIVE_MARGINAL) return "marginal";
  return "no";
}

const VERDICT_STYLE: Record<FitVerdict, string> = {
  green: "border-emerald-200 bg-emerald-50 text-emerald-700",
  yellow: "border-amber-200 bg-amber-50 text-amber-800",
  red: "border-red-200 bg-red-50 text-red-700",
};
const VERDICT_LABEL: Record<FitVerdict, string> = { green: "Keeps up", yellow: "Tight", red: "Too slow" };
const POST_CALL_LABEL: Record<FitVerdict, string> = { green: "Fine", yellow: "Slow", red: "Too slow" };
const FEASIBILITY: Record<Exclude<FitFeasibility, "">, { label: string; cls: string }> = {
  feasible: { label: "Feasible", cls: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  marginal: { label: "Marginal", cls: "border-amber-200 bg-amber-50 text-amber-800" },
  no: { label: "Not feasible", cls: "border-red-200 bg-red-50 text-red-700" },
};

// A resolved, contention-aware view of one agent row.
interface RoleView {
  role: FitRole;
  budget: number;
  verdict: FitVerdict;
  recommended: number;
  changed: boolean;
}

interface LocalModelFitCardProps {
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
  const [contention, setContention] = useState(DEFAULT_CONTENTION);
  // Per-model, per-agent budget the user has set/applied: {model_id: {slug: seconds}}.
  const [budgets, setBudgets] = useState<Record<string, Record<string, number>>>({});

  const loadSummary = useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.getLocalFitSummary();
      setSummary(next);
      // Restore the last run: the test costs real time on a local model, so a
      // reload must not silently throw the results away.
      if (next.last_result) {
        setReport(next.last_result);
        setContention(next.last_result.contention || DEFAULT_CONTENTION);
      }
      setError(null);
    } catch (err) {
      console.error("Failed to load local fit summary", err);
      setError("Unable to load local models. The backend may still be starting.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadSummary(); }, [loadSummary]);
  useEffect(() => {
    if (!error || summary) return;
    const retry = window.setTimeout(() => { void loadSummary(); }, 3000);
    return () => window.clearTimeout(retry);
  }, [error, summary, loadSummary]);

  const runTest = async () => {
    setRunning(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.runLocalFit();
      setReport(result);
      setContention(result.contention || DEFAULT_CONTENTION);
      setBudgets({}); // start from the server's stored budgets
    } catch (err) {
      console.error("Local fit test failed", err);
      setError(err instanceof Error ? err.message : "Fit test failed.");
    } finally {
      setRunning(false);
    }
  };

  const budgetFor = useCallback(
    (modelId: string, role: FitRole) => budgets[modelId]?.[role.slug] ?? role.budget_seconds,
    [budgets],
  );

  const resolveRole = useCallback(
    (modelId: string, role: FitRole): RoleView => {
      const eff = effective(role.latency_seconds, contention);
      if (role.post_call) {
        return { role, budget: role.budget_seconds, verdict: classifyPostCall(eff), recommended: 0, changed: false };
      }
      const budget = budgetFor(modelId, role);
      const recommended = recommendInterval(eff, budget);
      return { role, budget, verdict: classifyLatency(eff, budget), recommended, changed: recommended !== budget };
    },
    [contention, budgetFor],
  );

  const persistBudget = async (modelId: string, slug: string, seconds: number) => {
    const clamped = Math.min(Math.max(Math.round(seconds), MIN_INTERVAL), MAX_INTERVAL);
    setBudgets((prev) => ({ ...prev, [modelId]: { ...prev[modelId], [slug]: clamped } }));
    try {
      await api.applyLocalFitIntervals(modelId, [{ slug, interval_seconds: clamped }]);
      onIntervalsApplied?.();
    } catch (err) {
      console.error("Saving budget failed", err);
      setError(err instanceof Error ? err.message : "Unable to save budget.");
    }
  };

  const applyRecommended = async (model: TextModelFit) => {
    const updates = model.roles
      .filter((r) => !r.post_call && r.editable)
      .map((r) => resolveRole(model.model_id, r))
      .filter((v) => v.changed)
      .map((v) => ({ slug: v.role.slug, interval_seconds: v.recommended }));
    if (updates.length === 0) return;
    setApplyingModel(model.model_id);
    setError(null);
    setNotice(null);
    try {
      const { applied } = await api.applyLocalFitIntervals(model.model_id, updates);
      setBudgets((prev) => ({ ...prev, [model.model_id]: { ...prev[model.model_id], ...applied } }));
      setNotice(`Applied ${Object.keys(applied).length} budget change(s) for ${model.model_name} (contention ${contention.toFixed(1)}x).`);
      onIntervalsApplied?.();
    } catch (err) {
      console.error("Applying budgets failed", err);
      setError(err instanceof Error ? err.message : "Unable to apply budgets.");
    } finally {
      setApplyingModel(null);
    }
  };

  // --- Transcription (ASR) manual measurement ---
  const [asrReport, setAsrReport] = useState<AsrFitReport | null>(null);
  const [asrBusy, setAsrBusy] = useState(false);
  const [asrError, setAsrError] = useState<string | null>(null);
  const measureAsr = useCallback(async (file: File) => {
    setAsrBusy(true);
    setAsrError(null);
    try {
      setAsrReport(await api.runAsrFit(file));
    } catch (err) {
      console.error("ASR fit failed", err);
      setAsrError(err instanceof Error ? err.message : "Transcription speed check failed.");
    } finally {
      setAsrBusy(false);
    }
  }, []);
  const [asrFile, setAsrFile] = useState<File | null>(null);
  const recorder = useClipRecorder({
    maxSeconds: MAX_ASR_RECORD_SECONDS,
    baseName: "asr-clip",
    onClip: (file) => { setAsrFile(file); void measureAsr(file); },
    onError: (message) => setAsrError(message),
  });

  const hasModels = summary?.has_local_text_models ?? false;
  const capabilities = summary?.capabilities ?? null;
  const usableForById = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const model of capabilities?.models ?? []) map[model.id] = model.usable_for;
    return map;
  }, [capabilities]);
  // Prefer a real-voice measurement; fall back to the auto synthetic-clip run.
  const asr = asrReport ?? report?.asr ?? null;
  const validity = report?.validity;
  const incompatible = validity?.status === "incompatible";
  const superseded = validity?.status === "superseded";

  return (
    <div className="rounded-xl bg-surface p-5 shadow-sm">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="font-display text-base font-bold text-brand-dark-gray">Local Model Fit Test</h3>
          <p className="mt-1 max-w-2xl font-body text-xs leading-relaxed text-brand-gray">
            Times a role-sized call on each local text model and the bundled ASR models, then checks whether
            each agent keeps up. Speed only, not answer quality.
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

      {capabilities && <LocalCapabilityMap capabilities={capabilities} />}

      {!loading && !hasModels && (
        <div className="mt-4 rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-3">
          <p className="font-body text-xs leading-relaxed text-brand-gray">
            No self-hosted text models found. Add an on-prem OpenAI-compatible endpoint (Ollama, LM Studio,
            vLLM, LiteLLM) under <span className="font-semibold text-brand-dark-gray">Connections</span> to test
            local analysis. The bundled ASR models are still tested below.
          </p>
        </div>
      )}

      {running && (
        <div className="mt-4 rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-3">
          <p className="font-body text-xs text-brand-gray">
            Running the fit test... timing each text model and the local ASR models. First run may download
            the ASR models.
          </p>
        </div>
      )}

      {(validity || report?.measured_at) && !running && (
        <p className={`mt-3 rounded border px-3 py-2 font-body text-xs ${
          validity?.status === "superseded"
            ? "border-amber-200 bg-amber-50 text-amber-800"
            : "border-brand-light-gray-1 bg-brand-light-gray-2/30 text-brand-gray"
        }`}>
          {validity?.status === "aged"
            ? validity.reason
            : (!validity || validity.status === "current") && report?.measured_at
              ? `Measured ${new Date(report.measured_at).toLocaleString()}`
              : validity?.reason}
        </p>
      )}

      {report && !running && !incompatible && (
        <>
          <ContentionSlider contention={contention} onChange={setContention} />
          <div className={`mt-3 space-y-4 ${superseded ? "opacity-60" : ""}`}>
            {report.text_models.map((model) => (
              <ModelFitBlock
                key={model.model_id}
                model={model}
                usableFor={usableForById[model.model_id] ?? []}
                contention={contention}
                applying={applyingModel === model.model_id}
                resolveRole={(role) => resolveRole(model.model_id, role)}
                onEditBudget={(slug, seconds) => setBudgets((prev) => ({ ...prev, [model.model_id]: { ...prev[model.model_id], [slug]: seconds } }))}
                onCommitBudget={(slug, seconds) => void persistBudget(model.model_id, slug, seconds)}
                onApply={() => void applyRecommended(model)}
              />
            ))}
          </div>
        </>
      )}

      {notice && (
        <p className="mt-3 rounded border border-emerald-200 bg-emerald-50 px-3 py-2 font-body text-xs text-emerald-800">{notice}</p>
      )}
      {error && (
        <p className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 font-body text-xs text-red-700">{error}</p>
      )}

      {/* Transcription keep-up (local ASR) */}
      <div className="mt-4 border-t border-brand-light-gray-1 pt-4">
        <div className="mb-2">
          <h4 className="font-display text-sm font-bold text-brand-dark-gray">Transcription keep-up (local ASR)</h4>
          <p className="mt-1 max-w-2xl font-body text-xs leading-relaxed text-brand-gray">
            Real-time factor for the bundled speech-to-text models. Run fit test measures them on a synthetic
            clip (an estimate); upload or record real speech for a precise number. Live-caption feasibility is
            experimental (see roadmap): a projection of whether a rolling-window local captioner could keep up.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <input
            type="file"
            accept=".m4a,.mp3,.wav,.ogg,.flac,.webm,audio/*"
            onChange={(e) => setAsrFile(e.target.files?.[0] ?? null)}
            disabled={asrBusy || recorder.recording}
            className="max-w-xs rounded border border-brand-light-gray-1 bg-surface px-3 py-1.5 font-body text-xs text-brand-dark-gray"
          />
          <button
            onClick={() => asrFile && void measureAsr(asrFile)}
            disabled={!asrFile || asrBusy || recorder.recording}
            className="rounded bg-brand-teal px-3 py-1.5 font-body text-xs font-medium text-white transition-colors hover:bg-brand-teal-dark disabled:cursor-not-allowed disabled:bg-brand-light-gray-1"
          >
            {asrBusy ? "Measuring..." : "Measure real speech"}
          </button>
          {recorder.supported && (
            <button
              onClick={recorder.recording ? recorder.stop : () => void recorder.start()}
              disabled={asrBusy && !recorder.recording}
              className="rounded border border-brand-teal px-3 py-1.5 font-body text-xs font-medium text-brand-teal transition-colors hover:bg-brand-teal hover:text-white disabled:cursor-not-allowed disabled:border-brand-light-gray-1 disabled:text-brand-mid-gray"
            >
              {recorder.recording ? `Stop (${recorder.seconds}s)` : "Record 15s clip"}
            </button>
          )}
        </div>

        {asr && (
          <div className="mt-3 overflow-x-auto rounded border border-brand-light-gray-1 p-3">
            <p className="mb-2 font-body text-[11px] text-brand-mid-gray">
              {asr.estimated ? "Estimated on a synthetic clip" : "Measured on real speech"} - {asr.audio_seconds.toFixed(1)}s of audio
            </p>
            <table className="w-full border-collapse font-body text-xs">
              <thead>
                <tr className="text-left text-brand-mid-gray">
                  <th className="py-1 pr-3 font-medium">Model</th>
                  <th className="py-1 pr-3 font-medium">Real-time factor</th>
                  <th className="py-1 pr-3 font-medium">Batch transcription</th>
                  <th className="py-1 font-medium">Live captions (exp.)</th>
                </tr>
              </thead>
              <tbody>
                {asr.asr_models.map((m) => (
                  <AsrRow key={m.model_id} model={m} contention={contention} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {asrError && (
          <p className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 font-body text-xs text-red-700">{asrError}</p>
        )}
      </div>

      <div className="mt-4 rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-2">
        <p className="font-body text-xs leading-relaxed text-brand-gray">
          To run an agent on a local model, also select it on the Agents tab. Budgets you set here are
          per-model: the agent uses this budget only when it runs that model. Live interim captions have no
          local option today (they need a cloud streaming model).
        </p>
      </div>
    </div>
  );
}

function ContentionSlider({ contention, onChange }: { contention: number; onChange: (c: number) => void }) {
  return (
    <div className="mt-4 rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-body text-[10px] font-semibold uppercase tracking-wide text-brand-mid-gray">Assumed load headroom</p>
          <p className="mt-0.5 font-body text-xs text-brand-gray">
            Reserve for recording, diarization, and other apps: <span className="font-semibold text-brand-dark-gray">{contention.toFixed(1)}x</span> measured latency
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-body text-[10px] text-brand-mid-gray">1x</span>
          <input
            type="range"
            min={MIN_CONTENTION}
            max={MAX_CONTENTION}
            step={0.1}
            value={contention}
            onChange={(e) => onChange(Number(e.target.value))}
            className="w-48 accent-brand-teal"
          />
          <span className="font-body text-[10px] text-brand-mid-gray">3x</span>
        </div>
      </div>
    </div>
  );
}

function ModelFitBlock({
  model,
  usableFor,
  contention,
  applying,
  resolveRole,
  onEditBudget,
  onCommitBudget,
  onApply,
}: {
  model: TextModelFit;
  usableFor: string[];
  contention: number;
  applying: boolean;
  resolveRole: (role: FitRole) => RoleView;
  onEditBudget: (slug: string, seconds: number) => void;
  onCommitBudget: (slug: string, seconds: number) => void;
  onApply: () => void;
}) {
  const views = model.status === "ok" ? model.roles.map(resolveRole) : [];
  const changes = views.filter((v) => v.changed).length;
  const superseded = model.validity?.status === "superseded";

  return (
    <div className={`rounded-lg border border-brand-light-gray-1 p-4 ${superseded ? "opacity-60" : ""}`}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-display text-sm font-bold text-brand-dark-gray" title={model.model_id}>{model.model_name}</p>
          {superseded && (
            <span className="mt-1 inline-flex rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 font-body text-[10px] text-amber-800">
              Superseded
            </span>
          )}
          {model.status === "ok" && model.short && model.long ? (
            <p className="mt-0.5 font-body text-[11px] text-brand-mid-gray">
              Short {model.short.latency_seconds.toFixed(1)}s - Long {model.long.latency_seconds.toFixed(1)}s per call
            </p>
          ) : (
            <p className="mt-0.5 font-body text-[11px] text-red-700">{model.reason || "Benchmark failed."}</p>
          )}
          {usableFor.length > 0 && (
            <p className="mt-0.5 font-body text-[11px] text-brand-mid-gray">Usable for: <span className="text-brand-gray">{usableFor.join(", ")}</span></p>
          )}
        </div>
        {model.status === "ok" && changes > 0 && !superseded && (
          <button
            onClick={onApply}
            disabled={applying}
            className="rounded bg-brand-teal px-3 py-1.5 font-body text-xs font-medium text-white transition-colors hover:bg-brand-teal-dark disabled:cursor-not-allowed disabled:bg-brand-light-gray-1"
          >
            {applying ? "Applying..." : `Apply recommended budgets (${changes})`}
          </button>
        )}
      </div>

      {views.length > 0 && (
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
              {views.map((view) => (
                <RoleRow
                  key={view.role.slug}
                  view={view}
                  contention={contention}
                  onEditBudget={onEditBudget}
                  onCommitBudget={onCommitBudget}
                  suppressRecommendation={superseded}
                />
              ))}
            </tbody>
          </table>
          <p className="mt-2 font-body text-[10px] text-brand-mid-gray">
            Briefing agents run once at call end (no live loop), so they show an acceptable-wait verdict, not a cycle budget.
          </p>
        </div>
      )}
    </div>
  );
}

function RoleRow({
  view,
  contention,
  onEditBudget,
  onCommitBudget,
  suppressRecommendation,
}: {
  view: RoleView;
  contention: number;
  onEditBudget: (slug: string, seconds: number) => void;
  onCommitBudget: (slug: string, seconds: number) => void;
  suppressRecommendation: boolean;
}) {
  const { role, budget, verdict, recommended, changed } = view;
  const eff = effective(role.latency_seconds, contention);
  return (
    <tr className="border-t border-brand-light-gray-1">
      <td className="py-1.5 pr-3 text-brand-dark-gray">
        {role.name}
        {role.post_call && <span className="ml-1 text-[10px] text-brand-mid-gray">(post-call)</span>}
      </td>
      <td className="py-1.5 pr-3 capitalize text-brand-gray">{role.prompt_profile}</td>
      <td className="py-1.5 pr-3 text-brand-gray" title={`${eff.toFixed(1)}s at ${contention.toFixed(1)}x load`}>{role.latency_seconds.toFixed(1)}s</td>
      <td className="py-1.5 pr-3 text-brand-gray">
        {role.post_call ? (
          <span className="text-brand-mid-gray">end-of-call</span>
        ) : role.editable ? (
          <input
            type="number"
            min={MIN_INTERVAL}
            max={MAX_INTERVAL}
            value={budget}
            onChange={(e) => { const v = parseInt(e.target.value, 10); if (!Number.isNaN(v)) onEditBudget(role.slug, v); }}
            onBlur={(e) => { const v = parseInt(e.target.value, 10); if (!Number.isNaN(v)) onCommitBudget(role.slug, v); }}
            className="w-16 rounded border border-brand-light-gray-1 bg-surface px-2 py-0.5 text-xs text-brand-dark-gray focus:border-brand-teal"
          />
        ) : (
          <span>{budget}s</span>
        )}
      </td>
      <td className="py-1.5 pr-3">
        <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold ${VERDICT_STYLE[verdict]}`}>
          {(role.post_call ? POST_CALL_LABEL : VERDICT_LABEL)[verdict]}
        </span>
      </td>
      <td className="py-1.5 text-brand-gray">
        {suppressRecommendation ? (
          <span className="text-brand-mid-gray">-</span>
        ) : role.post_call ? (
          <span className="text-brand-mid-gray">-</span>
        ) : changed ? (
          <span className="font-semibold text-brand-teal">{recommended}s</span>
        ) : (
          <span className="text-brand-mid-gray">no change</span>
        )}
      </td>
    </tr>
  );
}

function AsrRow({ model, contention }: { model: AsrModelFit; contention: number }) {
  if (model.status !== "ok" || model.real_time_factor == null) {
    return (
      <tr className="border-t border-brand-light-gray-1">
        <td className="py-1.5 pr-3 text-brand-dark-gray">{model.model_name}</td>
        <td className="py-1.5 pr-3 text-brand-mid-gray" colSpan={3}>{model.reason || "Benchmark failed."}</td>
      </tr>
    );
  }
  const effRtf = effective(model.real_time_factor, contention);
  const verdict = classifyRtf(effRtf);
  const feasibility = model.short_real_time_factor != null
    ? classifyFeasibility(effective(model.short_real_time_factor, contention))
    : "";
  return (
    <tr className="border-t border-brand-light-gray-1">
      <td className="py-1.5 pr-3 text-brand-dark-gray">{model.model_name}</td>
      <td className="py-1.5 pr-3 text-brand-gray" title={`${effRtf.toFixed(2)}x at ${contention.toFixed(1)}x load`}>{model.real_time_factor.toFixed(2)}x</td>
      <td className="py-1.5 pr-3">
        <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold ${VERDICT_STYLE[verdict]}`}>{VERDICT_LABEL[verdict]}</span>
      </td>
      <td className="py-1.5">
        {feasibility ? (
          <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold ${FEASIBILITY[feasibility].cls}`}>{FEASIBILITY[feasibility].label}</span>
        ) : (
          <span className="text-brand-mid-gray">-</span>
        )}
      </td>
    </tr>
  );
}

function LocalCapabilityMap({ capabilities }: { capabilities: LocalCapabilities }) {
  return (
    <div className="mt-4 rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-3">
      <p className="mb-2 font-body text-[10px] font-semibold uppercase tracking-wide text-brand-mid-gray">What can run locally on this machine</p>
      <ul className="space-y-1.5">
        {capabilities.services.map((service) => (
          <li key={service.key} className="flex flex-wrap items-baseline gap-x-2 font-body text-xs">
            <span className="font-medium text-brand-dark-gray">{service.label}:</span>
            {service.cloud_only ? (
              <span className="text-amber-700">no local option{service.note ? ` - ${service.note}` : ""}</span>
            ) : (
              <span className="text-brand-gray">{service.local_options.map((o) => o.name).join(", ")}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
