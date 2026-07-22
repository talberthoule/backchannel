import { useState, useRef, useEffect } from "react";
import type { Session, Speaker } from "../types";
import * as api from "../services/api";

interface SpeakerNameMapperProps {
  session: Session;
  speakers: Speaker[];
  onRefresh: () => void;
  onRefreshSession: () => void;
  onRefreshQuestions: () => void;
  onRefreshSynthesis: () => Promise<unknown>;
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
  disabled = false,
  disabledReason,
}: SpeakerNameMapperProps) {
  const [enhancing, setEnhancing] = useState(false);
  const [enhancementMessage, setEnhancementMessage] = useState("");
  const [enhancementError, setEnhancementError] = useState("");

  if (speakers.length === 0) return null;

  const handleEnhance = async () => {
    if (disabled || !session.speaker_context_dirty) return;
    if (!confirm("Enhance Insights will revalidate the Briefing and every Insight using the corrected speaker names and internal/external roles. Continue?")) {
      return;
    }
    setEnhancementMessage("");
    setEnhancementError("");
    setEnhancing(true);
    try {
      const result = await api.enhanceInsights(session.id);
      await Promise.all([
        onRefreshQuestions(),
        onRefreshSession(),
        onRefresh(),
        onRefreshSynthesis(),
      ]);
      setEnhancementMessage(
        result.briefing_updated
          ? `Revalidated the Briefing and all Insights; ${result.enhanced_insights} insight${result.enhanced_insights === 1 ? "" : "s"} changed.`
          : `Revalidated all Insights; ${result.enhanced_insights} changed, but the Briefing was not regenerated.`,
      );
    } catch (error) {
      setEnhancementError(error instanceof Error ? error.message : "Enhancement failed. Try again.");
    } finally {
      setEnhancing(false);
    }
  };

  return (
    <div className="rounded-xl bg-surface p-5 shadow-sm">
      <div className="mb-4 flex flex-col items-start justify-between gap-3 sm:flex-row">
        <div className="min-w-0">
          <h3 className="font-display text-sm font-semibold text-brand-dark-gray">
            Speaker Name Mapping
          </h3>
          <p className="font-body text-xs text-brand-mid-gray mt-0.5">
            Map auto-detected speakers to real names. Toggle each mapping on or off individually.
          </p>
          <p className="mt-1 font-body text-xs text-brand-gray">
            Correct speaker names and roles first. Enhance Insights uses these associations to
            reframe the Briefing and every Insight from the correct internal or external perspective.
          </p>
          {session.speaker_context_dirty ? (
            <p className="mt-1 font-body text-xs font-medium text-brand-amber">
              Speaker context changed since the last enhancement run.
            </p>
          ) : session.speaker_context_enhanced_at ? (
            <p className="mt-1 font-body text-xs text-brand-mid-gray">
              Last enhanced {new Date(session.speaker_context_enhanced_at).toLocaleString()}
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
          disabled={disabled || enhancing || !session.speaker_context_dirty}
          className={`shrink-0 rounded-md px-3 py-2 font-body text-sm font-semibold transition-colors ${
            session.speaker_context_dirty && !enhancing && !disabled
              ? "bg-brand-teal text-white hover:bg-brand-teal-dark"
              : "cursor-not-allowed bg-brand-light-gray-2 text-brand-mid-gray"
          }`}
        >
          {enhancing ? "Enhancing..." : "Enhance Insights"}
        </button>
      </div>

      {enhancementMessage && (
        <p className="mb-3 rounded-md bg-brand-teal/10 px-3 py-2 font-body text-xs text-brand-teal" role="status">
          {enhancementMessage}
        </p>
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
  const [displayName, setDisplayName] = useState(speaker.display_name || "");
  const [mergeTargetId, setMergeTargetId] = useState("");
  const [merging, setMerging] = useState(false);
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
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
    if (!confirm(`Merge ${sourceLabel} into ${targetLabel}? Transcript and insight attribution will move to ${targetLabel}.`)) {
      return;
    }

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
            You
          </span>
        )}
        <span
          className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium shrink-0 ${
            speaker.speaker_type === "team"
              ? "bg-brand-teal-light/10 text-brand-teal-light"
              : "bg-brand-light-gray-2 text-brand-gray"
          }`}
        >
          {speaker.speaker_type === "team" ? "Team" : "External party"}
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
            aria-label={`Mapped name for ${speaker.name}`}
            placeholder="Enter real name..."
            className="w-full rounded border border-brand-teal-light bg-surface px-2 py-1 text-sm text-brand-dark-gray ring-1 ring-brand-teal-light/30"
          />
        ) : (
          <button
            type="button"
            onClick={() => {
              if (!disabled) setEditing(true);
            }}
            disabled={disabled}
            aria-label={`Edit mapped name for ${speaker.name}`}
            className={`block w-full break-words rounded px-2 py-1 text-left text-sm transition-colors ${
              disabled ? "cursor-not-allowed" : "cursor-pointer hover:bg-brand-light-gray-2"
            } ${
              hasMapping
                ? speaker.display_name_enabled
                  ? "font-medium text-brand-dark-gray"
                  : "text-brand-mid-gray line-through"
                : "italic text-brand-mid-gray"
            }`}
            title={hasMapping ? speaker.display_name : "Click to map a real name"}
          >
            {hasMapping ? speaker.display_name : "Click to map a real name..."}
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
        aria-label={`Classification for ${speaker.name}`}
        className="shrink-0 rounded border border-brand-light-gray-1 bg-surface px-2 py-1 font-body text-xs text-brand-gray focus:border-brand-teal-light disabled:cursor-not-allowed disabled:bg-brand-light-gray-2"
        title="Speaker type used by analysis agents"
      >
        <option value="team">Team</option>
        <option value="external">External party</option>
      </select>

      {mergeTargets.length > 0 && (
        <div className="flex min-w-0 items-center gap-1">
          <select
            value={mergeTargetId}
            onChange={(e) => setMergeTargetId(e.target.value)}
            disabled={disabled}
            aria-label={`Merge target for ${speaker.name}`}
            className="min-w-0 max-w-48 rounded border border-brand-light-gray-1 bg-surface px-2 py-1 font-body text-xs text-brand-gray focus:border-brand-teal-light disabled:cursor-not-allowed disabled:bg-brand-light-gray-2"
            title="Merge this detected speaker into another speaker"
          >
            <option value="">Merge into...</option>
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
            {merging ? "Merging" : "Merge"}
          </button>
        </div>
      )}

      {/* Toggle */}
      <button
        type="button"
        onClick={handleToggle}
        disabled={disabled || !hasMapping}
        aria-label={`${speaker.display_name_enabled ? "Disable" : "Enable"} mapped name for ${speaker.name}`}
        aria-pressed={speaker.display_name_enabled}
        className={`h-5 w-9 rounded-full transition-colors shrink-0 ${
          hasMapping && speaker.display_name_enabled ? "bg-brand-teal" : "bg-brand-light-gray-1"
        } ${disabled || !hasMapping ? "opacity-30 cursor-not-allowed" : ""}`}
        title={
          !hasMapping
            ? "Set a display name first"
            : speaker.display_name_enabled
              ? "Enabled — using mapped name in UI and exports"
              : "Disabled — using original speaker label"
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
