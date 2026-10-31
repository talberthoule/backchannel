import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import type { AgentConfig, EnhanceInsightsResult, ModelInfo, Session, Speaker } from "../types";
import * as api from "../services/api";
import { useConfirm } from "./ConfirmProvider";
import i18n from "../i18n";

export function enhancementOutcome(result: EnhanceInsightsResult): {
  tone: "success" | "warning";
  message: string;
} {
  if (
    result.status === "completed"
    && result.briefing_updated
    && result.briefing_status === "completed"
    && !result.speaker_context_dirty
  ) {
    return {
      tone: "success",
      message: i18n.t("speakerMapper.outcomeSuccess", { count: result.enhanced_insights }),
    };
  }
  return {
    tone: "warning",
    message: result.error || i18n.t("speakerMapper.outcomeFailed"),
  };
}

export function enhancementProgressLabel(
  result: Pick<EnhanceInsightsResult, "status" | "completed_batches" | "total_batches">,
): string {
  return result.status === "running"
    ? i18n.t("speakerMapper.progress", {
        done: result.completed_batches,
        total: result.total_batches,
      })
    : "";
}

export function shouldOfferRetry(
  result: Pick<EnhanceInsightsResult, "status"> | null,
): boolean {
  return !!result && (result.status === "partial" || result.status === "failed");
}

export function modelBindingLabel(
  agents: Array<Pick<AgentConfig, "slug" | "model_id">>,
  models: Array<Pick<ModelInfo, "id" | "name">>,
): string {
  const modelId = agents.find((agent) => agent.slug === "synthesizer")?.model_id || "";
  if (!modelId) return i18n.t("speakerMapper.notSelected");
  const name = models.find((model) => model.id === modelId)?.name;
  return name ? `${name} (${modelId})` : modelId;
}

export function enhancementRunModels(
  result: Pick<EnhanceInsightsResult, "batches"> | null,
): {
  requested: string[];
  actual: string[];
  usedFallback: boolean;
  recorded: boolean;
} {
  const batches = result?.batches.filter((batch) => batch.kind === "insights") ?? [];
  const requested = [...new Set(batches.map((batch) => batch.requested_model_id).filter((id): id is string => !!id))];
  const actual = [...new Set(batches.map((batch) => batch.model_id).filter((id): id is string => !!id))];
  return {
    requested,
    actual,
    usedFallback: batches.some(
      (batch) => !!batch.requested_model_id && !!batch.model_id && batch.requested_model_id !== batch.model_id,
    ),
    recorded: actual.length > 0,
  };
}

function EnhancementModelStatus({
  loaded,
  modelId,
  models,
  loadError,
  latest,
  onOpenAdminAgents,
}: {
  loaded: boolean;
  modelId: string;
  models: ModelInfo[];
  loadError: string;
  latest: EnhanceInsightsResult | null;
  onOpenAdminAgents: () => void;
}) {
  const { t } = useTranslation();
  const label = loaded
    ? modelBindingLabel([{ slug: "synthesizer", model_id: modelId }], models)
    : t("speakerMapper.loading");
  const run = enhancementRunModels(latest);
  const displayModel = (id: string) => {
    const name = models.find((model) => model.id === id)?.name;
    return name ? `${name} (${id})` : id;
  };

  return (
    <>
      <p className="mt-2 font-body text-xs text-brand-gray">
        {t("speakerMapper.usesSynthesizer")} <span className="font-semibold text-brand-dark-gray">{label}</span>{" "}
        <button type="button" onClick={onOpenAdminAgents} className="font-semibold text-brand-teal underline underline-offset-2">
          {t("speakerMapper.openAdmin")}
        </button>
      </p>
      <p className="mt-1 font-body text-xs text-brand-mid-gray">
        {t("speakerMapper.briefingModels")}
      </p>
      {loaded && !modelId && (
        <p className="mt-1 font-body text-xs font-medium text-brand-amber" role="alert">
          {loadError || t("speakerMapper.selectSynthesizer")}
        </p>
      )}
      {latest && run.recorded && (
        <p className="mt-1 font-body text-xs text-brand-mid-gray">
          {t("speakerMapper.latestRun", {
            models: run.actual.map(displayModel).join(", "),
            fallback: run.usedFallback
              ? t("speakerMapper.fallback", { models: run.requested.map(displayModel).join(", ") })
              : "",
          })}
        </p>
      )}
      {latest && !run.recorded && latest.batches.some((batch) => batch.kind === "insights") && (
        <p className="mt-1 font-body text-xs text-brand-mid-gray">
          {t("speakerMapper.noRecordedModel")}
        </p>
      )}
    </>
  );
}

interface SpeakerNameMapperProps {
  session: Session;
  speakers: Speaker[];
  onRefresh: () => void;
  onRefreshSession: () => void;
  onRefreshQuestions: () => void;
  onRefreshSynthesis: () => Promise<unknown>;
  onOpenAdminAgents: () => void;
  disabled?: boolean;
  disabledReason?: string;
}

export default function SpeakerNameMapper({
  session,
  speakers,
  onRefresh,
  onRefreshSession,
  onRefreshQuestions,
  onRefreshSynthesis,
  onOpenAdminAgents,
  disabled = false,
  disabledReason,
}: SpeakerNameMapperProps) {
  const { t } = useTranslation();
  const [enhancing, setEnhancing] = useState(false);
  const [enhancementMessage, setEnhancementMessage] = useState("");
  const [enhancementWarning, setEnhancementWarning] = useState("");
  const [enhancementError, setEnhancementError] = useState("");
  const [lastResult, setLastResult] = useState<EnhanceInsightsResult | null>(null);
  const [agentsLoaded, setAgentsLoaded] = useState(false);
  const [synthesizerModelId, setSynthesizerModelId] = useState("");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelLoadError, setModelLoadError] = useState("");
  const { confirm } = useConfirm();

  useEffect(() => {
    let cancelled = false;
    void Promise.allSettled([
      api.listAgents(),
      api.listModels(),
      api.getLatestEnhancement(session.id),
    ]).then(([agentsResult, modelsResult, latestResult]) => {
      if (cancelled) return;
      if (modelsResult.status === "fulfilled") setModels(modelsResult.value);
      if (agentsResult.status === "fulfilled") {
        setSynthesizerModelId(
          agentsResult.value.find((agent) => agent.slug === "synthesizer")?.model_id || "",
        );
      } else {
        setModelLoadError(t("speakerMapper.modelBindingFailed"));
      }
      setAgentsLoaded(true);
      if (latestResult.status === "fulfilled") setLastResult(latestResult.value);
    });
    return () => {
      cancelled = true;
    };
  }, [session.id]);

  if (speakers.length === 0) return null;

  const runEnhancement = async () => {
    setEnhancementMessage("");
    setEnhancementWarning("");
    setEnhancementError("");
    setLastResult(null);
    setEnhancing(true);
    try {
      const initial = await api.enhanceInsights(session.id);
      const result = await api.waitForEnhancement(
        session.id,
        initial,
        (progress) => setEnhancementMessage(enhancementProgressLabel(progress)),
      );
      await Promise.all([
        onRefreshQuestions(),
        onRefreshSession(),
        onRefresh(),
        onRefreshSynthesis(),
      ]);
      setLastResult(result);
      const outcome = enhancementOutcome(result);
      if (outcome.tone === "success") {
        setEnhancementMessage(outcome.message);
        setEnhancementWarning("");
      } else {
        // The run is finished: drop the stale "Revalidating x/y batches..."
        // progress banner so it cannot contradict the failure notice.
        setEnhancementMessage("");
        setEnhancementWarning(outcome.message);
      }
    } catch (error) {
      setEnhancementMessage("");
      setEnhancementError(error instanceof Error ? error.message : t("speakerMapper.enhanceFailed"));
    } finally {
      setEnhancing(false);
    }
  };

  const handleEnhance = async () => {
    if (disabled || !session.speaker_context_dirty || !synthesizerModelId) return;
    const ok = await confirm({
      title: t("speakerMapper.confirmTitle"),
      message: t("speakerMapper.confirmMessage"),
      confirmLabel: t("speakerMapper.continue"),
      tone: "default",
    });
    if (!ok) return;
    await runEnhancement();
  };

  const handleRetry = async () => {
    if (disabled || enhancing || !session.speaker_context_dirty || !synthesizerModelId) return;
    await runEnhancement();
  };

  const offerRetry =
    shouldOfferRetry(lastResult)
    && !enhancing
    && !disabled
    && session.speaker_context_dirty;
  const modelBlocked = !agentsLoaded || !synthesizerModelId;

  return (
    <div className="rounded-xl bg-surface p-5 shadow-sm">
      <div className="mb-4 flex flex-col items-start justify-between gap-3 sm:flex-row">
        <div className="min-w-0">
          <h3 className="font-display text-sm font-semibold text-brand-dark-gray">
            {t("speakerMapper.title")}
          </h3>
          <p className="font-body text-xs text-brand-mid-gray mt-0.5">
            {t("speakerMapper.body")}
          </p>
          <p className="mt-1 font-body text-xs text-brand-gray">
            {t("speakerMapper.instructions")}
          </p>
          <EnhancementModelStatus
            loaded={agentsLoaded}
            modelId={synthesizerModelId}
            models={models}
            loadError={modelLoadError}
            latest={lastResult}
            onOpenAdminAgents={onOpenAdminAgents}
          />
          {session.speaker_context_dirty ? (
            <p className="mt-1 font-body text-xs font-medium text-brand-amber">
              {t("speakerMapper.changed")}
            </p>
          ) : session.speaker_context_enhanced_at ? (
            <p className="mt-1 font-body text-xs text-brand-mid-gray">
              {t("speakerMapper.lastEnhanced", { date: new Date(session.speaker_context_enhanced_at).toLocaleString() })}
            </p>
          ) : null}
          {disabled && disabledReason && (
            <p className="mt-1 font-body text-xs font-medium text-brand-amber">
              {disabledReason}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={handleEnhance}
          disabled={disabled || enhancing || !session.speaker_context_dirty || modelBlocked}
          className={`shrink-0 rounded-md px-3 py-2 font-body text-sm font-semibold transition-colors ${
            session.speaker_context_dirty && !enhancing && !disabled && !modelBlocked
              ? "bg-brand-teal text-white hover:bg-brand-teal-dark"
              : "cursor-not-allowed bg-brand-light-gray-2 text-brand-mid-gray"
          }`}
        >
          {enhancing ? t("speakerMapper.enhancing") : t("speakerMapper.enhance")}
        </button>
      </div>

      {enhancementMessage && (
        <p className="mb-3 rounded-md bg-brand-teal/10 px-3 py-2 font-body text-xs text-brand-teal" role="status">
          {enhancementMessage}
        </p>
      )}
      {enhancementWarning && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-md bg-brand-amber/10 px-3 py-2" role="alert">
          <p className="min-w-0 flex-1 font-body text-xs text-brand-amber">
            {enhancementWarning}
          </p>
          {offerRetry && (
            <button
              type="button"
              onClick={handleRetry}
              className="shrink-0 rounded border border-brand-amber px-2 py-1 font-body text-xs font-semibold text-brand-amber transition-colors hover:bg-brand-amber/20"
            >
              {t("speakerMapper.retryBatches")}
            </button>
          )}
        </div>
      )}
      {enhancementError && (
        <p className="mb-3 rounded-md bg-red-500/10 px-3 py-2 font-body text-xs text-red-600" role="alert">
          {enhancementError}
        </p>
      )}

      <div className="space-y-2">
        {speakers.map((speaker) => (
          <SpeakerRow
            key={speaker.id}
            sessionId={session.id}
            speaker={speaker}
            speakers={speakers}
            disabled={disabled}
            onRefresh={async () => {
              await Promise.all([onRefresh(), onRefreshSession()]);
            }}
          />
        ))}
      </div>
    </div>
  );
}

function SpeakerRow({
  sessionId,
  speaker,
  speakers,
  disabled,
  onRefresh,
}: {
  sessionId: string;
  speaker: Speaker;
  speakers: Speaker[];
  disabled: boolean;
  onRefresh: () => void;
}) {
  const { t } = useTranslation();
  const [displayName, setDisplayName] = useState(speaker.display_name || "");
  const [mergeTargetId, setMergeTargetId] = useState("");
  const [merging, setMerging] = useState(false);
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const { confirm } = useConfirm();
  const mergeTargets = speakers.filter((candidate) => candidate.id !== speaker.id);

  useEffect(() => {
    setDisplayName(speaker.display_name || "");
  }, [speaker.display_name]);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  const handleSave = async () => {
    setEditing(false);
    if (disabled) return;
    const trimmed = displayName.trim();
    if (trimmed !== (speaker.display_name || "")) {
      await api.updateSpeaker(sessionId, speaker.id, {
        display_name: trimmed,
        display_name_enabled: trimmed ? speaker.display_name_enabled || true : false,
      });
      onRefresh();
    }
  };

  const handleToggle = async () => {
    if (disabled) return;
    if (!speaker.display_name) return; // nothing to toggle
    await api.updateSpeaker(sessionId, speaker.id, {
      display_name_enabled: !speaker.display_name_enabled,
    });
    onRefresh();
  };

  const handleSpeakerTypeChange = async (speakerType: "team" | "external") => {
    if (disabled) return;
    await api.updateSpeaker(sessionId, speaker.id, {
      speaker_type: speakerType,
      is_user: speakerType === "external" ? false : speaker.is_user,
    });
    onRefresh();
  };

  const handleMerge = async () => {
    if (disabled) return;
    const target = speakers.find((candidate) => candidate.id === mergeTargetId);
    if (!target) return;

    const sourceLabel = displayLabel(speaker);
    const targetLabel = displayLabel(target);
    const ok = await confirm({
      title: t("speakerMapper.mergeTitle"),
      message: t("speakerMapper.mergeMessage", { source: sourceLabel, target: targetLabel }),
      confirmLabel: t("speakerMapper.merge"),
      tone: "danger",
    });
    if (!ok) return;

    setMerging(true);
    try {
      await api.mergeSpeaker(sessionId, speaker.id, target.id);
      onRefresh();
    } finally {
      setMerging(false);
    }
  };

  const hasMapping = !!speaker.display_name;

  return (
    <div className={`flex flex-wrap items-center gap-3 rounded-lg border border-brand-light-gray-1 px-3 py-3 transition-colors ${
      disabled ? "bg-brand-light-gray-2/40 opacity-80" : "hover:bg-brand-light-gray-2/30"
    }`}>
      {/* Color dot + original name */}
      <div className="flex min-w-[14rem] flex-1 flex-wrap items-center gap-2">
        <span
          className="h-3 w-3 rounded-full shrink-0"
          style={{ backgroundColor: speaker.color }}
        />
        <span className="min-w-[8rem] flex-1 break-words font-body text-sm font-medium text-brand-dark-gray" title={speaker.name}>
          {speaker.name}
        </span>
        {speaker.is_user && (
          <span className="rounded-full bg-brand-teal/10 px-1.5 py-0.5 text-[10px] font-medium text-brand-teal shrink-0">
            {t("speakerMapper.you")}
          </span>
        )}
        <span
          className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium shrink-0 ${
            speaker.speaker_type === "team"
              ? "bg-brand-teal-light/10 text-brand-teal-light"
              : "bg-brand-light-gray-2 text-brand-gray"
          }`}
        >
          {speaker.speaker_type === "team" ? t("speakerMapper.team") : t("speakerMapper.external")}
        </span>
      </div>

      {/* Arrow */}
      <svg className="hidden h-4 w-4 shrink-0 text-brand-mid-gray sm:block" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5} aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
      </svg>

      {/* Display name (editable) */}
      <div className="min-w-[14rem] flex-[1.25]">
        {editing ? (
          <input
            ref={inputRef}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            onBlur={handleSave}
            disabled={disabled}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
              if (e.key === "Escape") {
                setDisplayName(speaker.display_name || "");
                setEditing(false);
              }
            }}
            aria-label={t("speakerMapper.mappedName", { name: speaker.name })}
            placeholder={t("speakerMapper.realName")}
            className="w-full rounded border border-brand-teal-light bg-surface px-2 py-1 text-sm text-brand-dark-gray ring-1 ring-brand-teal-light/30"
          />
        ) : (
          <button
            type="button"
            onClick={() => {
              if (!disabled) setEditing(true);
            }}
            disabled={disabled}
            aria-label={t("speakerMapper.editMapped", { name: speaker.name })}
            className={`block w-full break-words rounded px-2 py-1 text-left text-sm transition-colors ${
              disabled ? "cursor-not-allowed" : "cursor-pointer hover:bg-brand-light-gray-2"
            } ${
              hasMapping
                ? speaker.display_name_enabled
                  ? "font-medium text-brand-dark-gray"
                  : "text-brand-mid-gray line-through"
                : "italic text-brand-mid-gray"
            }`}
            title={hasMapping ? speaker.display_name : t("speakerMapper.clickMap")}
          >
            {hasMapping ? speaker.display_name : t("speakerMapper.clickMapShort")}
          </button>
        )}
      </div>

      {/* Role badge */}
      {speaker.role && (
        <span className="shrink-0 rounded-full bg-brand-light-gray-2 px-2 py-0.5 text-[10px] font-medium text-brand-gray">
          {speaker.role}
        </span>
      )}

      <select
        value={speaker.speaker_type}
        onChange={(e) => handleSpeakerTypeChange(e.target.value as "team" | "external")}
        disabled={disabled}
        aria-label={t("speakerMapper.classification", { name: speaker.name })}
        className="shrink-0 rounded border border-brand-light-gray-1 bg-surface px-2 py-1 font-body text-xs text-brand-gray focus:border-brand-teal-light disabled:cursor-not-allowed disabled:bg-brand-light-gray-2"
        title={t("speakerMapper.speakerTypeTitle")}
      >
        <option value="team">{t("speakerMapper.team")}</option>
        <option value="external">{t("speakerMapper.external")}</option>
      </select>

      {mergeTargets.length > 0 && (
        <div className="flex min-w-0 items-center gap-1">
          <select
            value={mergeTargetId}
            onChange={(e) => setMergeTargetId(e.target.value)}
            disabled={disabled}
            aria-label={t("speakerMapper.mergeTarget", { name: speaker.name })}
            className="min-w-0 max-w-48 rounded border border-brand-light-gray-1 bg-surface px-2 py-1 font-body text-xs text-brand-gray focus:border-brand-teal-light disabled:cursor-not-allowed disabled:bg-brand-light-gray-2"
            title={t("speakerMapper.mergeTargetTitle")}
          >
            <option value="">{t("speakerMapper.mergeInto")}</option>
            {mergeTargets.map((target) => (
              <option key={target.id} value={target.id}>
                {displayLabel(target)}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleMerge}
            disabled={disabled || !mergeTargetId || merging}
            className={`rounded border px-2 py-1 font-body text-xs font-medium transition-colors ${
              mergeTargetId && !merging && !disabled
                ? "border-brand-teal-light text-brand-teal-light hover:bg-brand-teal-light/10"
                : "cursor-not-allowed border-brand-light-gray-1 text-brand-mid-gray opacity-50"
            }`}
          >
            {merging ? t("speakerMapper.merging") : t("speakerMapper.merge")}
          </button>
        </div>
      )}

      {/* Toggle */}
      <button
        type="button"
        onClick={handleToggle}
        disabled={disabled || !hasMapping}
        aria-label={t("speakerMapper.toggleName", {
          action: speaker.display_name_enabled ? t("speakerMapper.disable") : t("speakerMapper.enable"),
          name: speaker.name,
        })}
        aria-pressed={speaker.display_name_enabled}
        className={`h-5 w-9 rounded-full transition-colors shrink-0 ${
          hasMapping && speaker.display_name_enabled ? "bg-brand-teal" : "bg-brand-light-gray-1"
        } ${disabled || !hasMapping ? "opacity-30 cursor-not-allowed" : ""}`}
        title={
          !hasMapping
            ? t("speakerMapper.setNameFirst")
            : speaker.display_name_enabled
              ? t("speakerMapper.enabledTitle")
              : t("speakerMapper.disabledTitle")
        }
      >
        <span
          className={`block h-4 w-4 rounded-full bg-surface shadow transition-transform ${
            hasMapping && speaker.display_name_enabled ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  );
}

function displayLabel(speaker: Speaker): string {
  return speaker.display_name && speaker.display_name_enabled ? speaker.display_name : speaker.name;
}
