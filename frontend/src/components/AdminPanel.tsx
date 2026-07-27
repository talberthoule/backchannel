import { useCallback, useEffect, useState } from "react";
import type { AgentConfig, AnalystLens, KnowledgeSource, ModelInfo, PrivacyConfig } from "../types";
import * as api from "../services/api";
import { groupModels, optionLabel, optionState, runsLocally } from "../lib/modelOptions";
import { useConfirm } from "./ConfirmProvider";
import DiarizationCapabilityCard from "./DiarizationCapabilityCard";
import BatchTranscriptionCard from "./BatchTranscriptionCard";
import LocalModelFitCard from "./LocalModelFitCard";
import ApiKeysCard from "./ApiKeysCard";
import EndpointsCard from "./EndpointsCard";
import PrivacyModeCard from "./PrivacyModeCard";
import ProviderOnboardingCard from "./ProviderOnboardingCard";
import AboutCard from "./AboutCard";
import type { DesktopUpdateController } from "../hooks/useDesktopUpdate";

const TYPE_BADGES: Record<string, { label: string; color: string }> = {
  audio: { label: "Audio", color: "#0d9488" },
  text: { label: "Text", color: "#7c3aed" },
  meta: { label: "Meta", color: "#f59e0b" },
  db: { label: "DB", color: "#10b981" },
};

// Backend default cadence per agent. Text agents run on a fixed cycle; the
// Principal Agent and Opportunity Specialist are event-driven, so their value
// is the minimum cooldown between runs.
const INTERVAL_DEFAULTS: Record<string, number> = {
  consolidated_analyst: 40,
  objection_handler: 10,
  synthesizer: 75,
  opportunity_specialist: 55,
  strategic_signals: 45,
};

// Grouped by when agents run, not by their internal type: the Principal
// Agent (meta) and Opportunity Specialist (db) react to live insights, while
// Strategic Signals cycles over the live context and the briefing trio runs
// only after a session or on demand. Slug order within a section is display order.
const AGENT_SECTIONS: { slugs: string[]; title: string; blurb: string }[] = [
  {
    slugs: ["audio_gateway"],
    title: "Listening",
    blurb: "Streams call audio to a silent live listener for instant interim transcription.",
  },
  {
    slugs: ["consolidated_analyst", "objection_handler", "synthesizer", "opportunity_specialist", "strategic_signals"],
    title: "Live Analysis",
    blurb: "Work the call as it happens: analysts surface and refine insights, specialists match them, and Strategic Signals keeps the live action cards current.",
  },
  {
    slugs: ["brief_meeting_lens", "brief_discovery_lens", "brief_arbiter"],
    title: "Post-Call Briefing",
    blurb: "Run after normal End Call or on demand: two independent lenses draft the briefing and the arbiter reconciles them into the final summary.",
  },
];

export type AdminTab = "agents" | "transcription" | "keys" | "about";

const TABS: { id: AdminTab; label: string; hint: string }[] = [
  { id: "agents", label: "Agents", hint: "Models, prompts, and behavior for each analysis agent" },
  { id: "transcription", label: "Transcription & Audio", hint: "Speaker diarization and batch transcription settings" },
  { id: "keys", label: "Connections", hint: "Connect AI providers and self-hosted model servers" },
  { id: "about", label: "About", hint: "Application version and release notes" },
];

interface AdminPanelProps {
  onBack: () => void;
  desktopUpdate: DesktopUpdateController;
  initialTab?: AdminTab;
  // Version this browser last ran before an upgrade; forwarded to the About
  // tab so releases since then are badged, with an unread dot on the tab.
  highlightSince?: string | null;
  // True only when opened from the welcome checklist's "Add API key" action:
  // the API Keys tab then leads with the contextual first-run setup card.
  // Direct entry through Administration stays the normal expert view.
  onboarding?: boolean;
  onOnboardingContinue?: () => void;
}

// Compact filter-chip toggle used for multi-select groups (knowledge sources,
// analyst lenses). Selected chips fill teal with a check; unselected chips stay
// muted outlines so large collections read as a quiet tag cloud.
function TogglePill({ label, selected, onToggle }: { label: string; selected: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={selected}
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 font-body text-xs transition-colors ${
        selected
          ? "border-brand-teal/40 bg-brand-teal/10 font-medium text-brand-teal"
          : "border-brand-light-gray-1 bg-surface text-brand-mid-gray hover:border-brand-mid-gray hover:text-brand-dark-gray"
      }`}
    >
      {selected && (
        <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      )}
      {label}
    </button>
  );
}

// Built-in insight types with special pipeline behavior; lenses can also
// surface findings as a custom type, which flows through the live view,
// post-call summary, and exports as its own first-class group.
const BUILTIN_LENS_TYPES: { value: string; label: string }[] = [
  { value: "question", label: "Question (tracks answers)" },
  { value: "observation", label: "Observation" },
  { value: "opportunity", label: "Opportunity (matches offerings)" },
  { value: "action_item", label: "Action Item" },
];
const BUILTIN_LENS_TYPE_VALUES = new Set(BUILTIN_LENS_TYPES.map((o) => o.value));
const CUSTOM_TYPE_SENTINEL = "__custom__";

// Mirror of the backend's item_type slug rules (lowercase letters, digits,
// underscores; must start with a letter; max 50 chars).
function slugifyTypeName(raw: string): string {
  const slug = raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^[0-9_]+/, "")
    .slice(0, 50);
  return slug || "custom";
}

function humanizeTypeSlug(slug: string): string {
  return slug.split("_").filter(Boolean).map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

function parseLenses(raw: string): AnalystLens[] {
  try {
    const data = JSON.parse(raw);
    return Array.isArray(data) ? data.filter((l): l is AnalystLens => !!l && typeof l === "object") : [];
  } catch {
    return [];
  }
}

// Editor for the Consolidated Analyst's configurable lenses. Each lens owns a
// prompt section that is concatenated into the system prompt's {lens_sections}
// placeholder when the lens is enabled; item_type picks the insight bucket its
// findings surface as.
function LensEditor({
  agent,
  onUpdate,
  onDraftChange,
}: {
  agent: AgentConfig;
  onUpdate: (slug: string, field: string, value: string | boolean | number | null) => void;
  onDraftChange: (slug: string, field: "prompt" | "interval_seconds" | "lenses", value: string | number) => void;
}) {
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const { confirm } = useConfirm();
  const lenses = parseLenses(agent.lenses);
  const missingPlaceholder = !agent.prompt.includes("{lens_sections}");

  const save = (next: AnalystLens[]) => onUpdate(agent.slug, "lenses", JSON.stringify(next));
  const draft = (next: AnalystLens[]) => onDraftChange(agent.slug, "lenses", JSON.stringify(next));
  const patched = (key: string, patch: Partial<AnalystLens>) =>
    lenses.map((l) => (l.key === key ? { ...l, ...patch } : l));

  const addLens = () => {
    let n = lenses.length + 1;
    while (lenses.some((l) => l.key === `lens-${n}`)) n += 1;
    const key = `lens-${n}`;
    save([...lenses, { key, label: "New Lens", item_type: "observation", enabled: true, prompt: "" }]);
    setExpandedKey(key);
  };

  const deleteLens = async (lens: AnalystLens) => {
    const ok = await confirm({
      title: "Delete lens",
      message: `Delete the "${lens.label}" lens and its prompt section?`,
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    if (expandedKey === lens.key) setExpandedKey(null);
    save(lenses.filter((l) => l.key !== lens.key));
  };

  return (
    <div className="border-t border-brand-light-gray-1/70 px-5 py-4">
      <div className="mb-2 flex items-center justify-between">
        <label className="block font-body text-xs font-medium text-brand-gray">Analysis Lenses</label>
        <button
          type="button"
          onClick={addLens}
          className="rounded-full border border-brand-light-gray-1 px-2.5 py-1 font-body text-[11px] font-medium text-brand-gray transition-colors hover:border-brand-teal hover:text-brand-teal"
        >
          + Add Lens
        </button>
      </div>

      <div className="space-y-1.5">
        {lenses.map((lens) => {
          const expanded = expandedKey === lens.key;
          const isBuiltinType = BUILTIN_LENS_TYPE_VALUES.has(lens.item_type);
          const typeBadge = isBuiltinType
            ? BUILTIN_LENS_TYPES.find((o) => o.value === lens.item_type)!.label.replace(/ \(.*\)$/, "")
            : humanizeTypeSlug(lens.item_type);
          const emptyPrompt = !lens.prompt.trim();
          return (
            <div key={lens.key} className={`rounded-lg border ${expanded ? "border-brand-teal/40" : "border-brand-light-gray-1"} bg-surface`}>
              <div className="flex items-center gap-2.5 px-3 py-2">
                <button
                  type="button"
                  role="switch"
                  aria-checked={lens.enabled}
                  title={lens.enabled ? "Lens is included in the prompt" : "Lens is excluded from the prompt"}
                  onClick={() => save(patched(lens.key, { enabled: !lens.enabled }))}
                  className={`h-4 w-7 shrink-0 rounded-full transition-colors ${lens.enabled ? "bg-brand-teal" : "bg-brand-light-gray-1"}`}
                >
                  <span className={`block h-3 w-3 rounded-full bg-surface shadow transition-transform ${lens.enabled ? "translate-x-3.5" : "translate-x-0.5"}`} />
                </button>
                <button
                  type="button"
                  onClick={() => setExpandedKey(expanded ? null : lens.key)}
                  aria-expanded={expanded}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                >
                  <span className={`truncate font-body text-xs font-medium ${lens.enabled ? "text-brand-dark-gray" : "text-brand-mid-gray"}`}>
                    {lens.label}
                  </span>
                  <span className="shrink-0 rounded-full bg-brand-light-gray-2 px-2 py-0.5 font-body text-[10px] text-brand-gray">
                    {typeBadge}
                  </span>
                  {emptyPrompt && (
                    <span className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 font-body text-[10px] text-amber-800" title="Lenses without a prompt section are skipped">
                      No prompt
                    </span>
                  )}
                  <svg className={`ml-auto h-3 w-3 shrink-0 text-brand-mid-gray transition-transform ${expanded ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                  </svg>
                </button>
                <button
                  type="button"
                  onClick={() => deleteLens(lens)}
                  title="Delete lens"
                  className="shrink-0 rounded p-1 text-brand-mid-gray transition-colors hover:bg-red-50 hover:text-red-600"
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                  </svg>
                </button>
              </div>

              {expanded && (
                <div className="space-y-3 border-t border-brand-light-gray-1/70 px-3 py-3">
                  <div className="grid gap-3 md:grid-cols-2">
                    <div>
                      <label className="mb-1 block font-body text-[10px] font-medium text-brand-gray">Lens Name</label>
                      <input
                        type="text"
                        value={lens.label}
                        onChange={(e) => draft(patched(lens.key, { label: e.target.value }))}
                        onBlur={(e) => save(patched(lens.key, { label: e.target.value.trim() || "Untitled Lens" }))}
                        className="w-full rounded border border-brand-light-gray-1 bg-surface px-2.5 py-1.5 font-body text-xs text-brand-dark-gray focus:border-brand-teal"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block font-body text-[10px] font-medium text-brand-gray">Findings Surface As</label>
                      <select
                        value={isBuiltinType ? lens.item_type : CUSTOM_TYPE_SENTINEL}
                        onChange={(e) => {
                          const v = e.target.value;
                          save(patched(lens.key, {
                            item_type: v === CUSTOM_TYPE_SENTINEL ? slugifyTypeName(lens.label) : v,
                          }));
                        }}
                        className="w-full rounded border border-brand-light-gray-1 bg-surface px-2.5 py-1.5 font-body text-xs text-brand-dark-gray focus:border-brand-teal"
                      >
                        {BUILTIN_LENS_TYPES.map((o) => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                        <option value={CUSTOM_TYPE_SENTINEL}>Custom type...</option>
                      </select>
                      {!isBuiltinType && (
                        <input
                          type="text"
                          value={lens.item_type}
                          onChange={(e) => draft(patched(lens.key, { item_type: e.target.value }))}
                          onBlur={(e) => save(patched(lens.key, { item_type: slugifyTypeName(e.target.value) }))}
                          placeholder="custom_type_name"
                          className="mt-1.5 w-full rounded border border-brand-light-gray-1 bg-surface px-2.5 py-1.5 font-mono text-xs text-brand-dark-gray focus:border-brand-teal"
                        />
                      )}
                      <p className="mt-1 font-body text-[10px] text-brand-mid-gray">
                        {isBuiltinType
                          ? "Built-in types plug into extra behaviors: Questions get answer tracking; Opportunities are picked up by the Opportunity Specialist agent for knowledge-source matching."
                          : "Custom types get their own filter chip, summary section, and export label. Lowercase letters, digits, and underscores. Not matched by the Opportunity Specialist."}
                      </p>
                    </div>
                  </div>
                  <div>
                    <label className="mb-1 block font-body text-[10px] font-medium text-brand-gray">Lens Prompt Section</label>
                    <textarea
                      value={lens.prompt}
                      onChange={(e) => draft(patched(lens.key, { prompt: e.target.value }))}
                      onBlur={(e) => save(patched(lens.key, { prompt: e.target.value }))}
                      rows={8}
                      placeholder="Describe what this lens should look for and how it should think..."
                      className="w-full resize-y rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-2 font-mono text-xs leading-relaxed text-brand-dark-gray focus:border-brand-teal"
                    />
                  </div>
                </div>
              )}
            </div>
          );
        })}
        {lenses.length === 0 && (
          <p className="rounded-lg border border-dashed border-brand-light-gray-1 px-3 py-4 text-center font-body text-xs text-brand-mid-gray">
            No lenses configured — the analyst will not produce insights. Add a lens to get started.
          </p>
        )}
      </div>

      <p className="mt-2 font-body text-[10px] text-brand-mid-gray">
        Each enabled lens adds its own numbered section to the system prompt (via the {"{lens_sections}"} placeholder) and tags its findings with the selected insight type. Toggling a lens off removes its section from the next call.
      </p>
      {missingPlaceholder && (
        <p className="mt-1 font-body text-[10px] text-amber-700">
          The system prompt below has no {"{lens_sections}"} placeholder, so lens sections are not inserted. Reset the prompt to default or add the placeholder where the lenses belong.
        </p>
      )}
    </div>
  );
}

function AgentCard({
  agent,
  models,
  knowledgeSources,
  isSaving,
  localOnly,
  onUpdate,
  onResetPrompt,
  onDraftChange,
}: {
  agent: AgentConfig;
  models: ModelInfo[];
  knowledgeSources: KnowledgeSource[];
  isSaving: boolean;
  localOnly: boolean;
  onUpdate: (slug: string, field: string, value: string | boolean | number | null) => void;
  onResetPrompt: (slug: string) => void;
  onDraftChange: (slug: string, field: "prompt" | "interval_seconds" | "lenses", value: string | number) => void;
}) {
  const [promptOpen, setPromptOpen] = useState(false);
  const badge = TYPE_BADGES[agent.agent_type] || TYPE_BADGES.text;
  const intervalDefault = agent.agent_type === "text" ? INTERVAL_DEFAULTS[agent.slug] ?? 15 : INTERVAL_DEFAULTS[agent.slug];
  const intervalDriven = agent.agent_type === "text" || agent.slug === "strategic_signals";
  const modelOptions = models.filter((m) => (agent.agent_type === "audio" ? m.supports_live_audio : m.supports_text));
  const hasLockedModels = modelOptions.some((m) => m.key_available === false);
  // Privacy First mode sidelines any agent that has no local model to run on.
  // A self-hosted text model counts, which is how the analysis agents keep
  // working with the mode on.
  const blockedByPrivacy = localOnly && !modelOptions.some(runsLocally);

  return (
    <div className={`rounded-xl bg-surface shadow-sm ring-1 ring-brand-light-gray-1/60 transition-opacity ${isSaving ? "opacity-70" : ""} ${agent.enabled && !blockedByPrivacy ? "" : "opacity-80"}`}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-4 px-5 pt-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-display text-base font-bold text-brand-dark-gray">{agent.name}</h3>
            <span className="inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium text-white" style={{ backgroundColor: badge.color }}>
              {badge.label}
            </span>
            <span className="font-mono text-[10px] text-brand-mid-gray">{agent.slug}</span>
            {!agent.enabled && (
              <span className="inline-flex rounded-full bg-brand-light-gray-1/80 px-2 py-0.5 text-[10px] font-medium text-brand-gray">
                Disabled
              </span>
            )}
            {agent.enabled && blockedByPrivacy && (
              <span className="inline-flex rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800">
                Inactive: Privacy First
              </span>
            )}
          </div>
          <p className="mt-1 font-body text-xs leading-relaxed text-brand-gray">{agent.description}</p>
          {agent.agent_type === "audio" && (
            <p className="mt-2 rounded border border-brand-light-gray-1 bg-brand-light-gray-2/60 px-2.5 py-1.5 font-body text-[11px] leading-relaxed text-brand-gray">
              This is the live audio bridge, so only live-audio models are listed. Self-hosted
              (OpenAI-compatible chat) models are text-only and do not appear here &mdash; they power the
              text analysis agents. For fully offline transcription, pick a local ONNX model in
              Transcription &amp; Audio.
            </p>
          )}
          {agent.slug === "opportunity_specialist" && (
            <p className="mt-2 rounded border border-brand-light-gray-1 bg-brand-light-gray-2/60 px-2.5 py-1.5 font-body text-[11px] leading-relaxed text-brand-gray">
              Runs downstream of the Consolidated Analyst: it does not find opportunities itself. When a lens surfaces a finding as an Opportunity, this agent matches it against the knowledge sources below and adds the match to the existing card. Only active for Client Sales and Customer Delivery meeting types.
            </p>
          )}
          {blockedByPrivacy && (
            <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-2.5 py-1.5 font-body text-[11px] leading-relaxed text-amber-900">
              Privacy First mode is on and this agent has no local model, so it will not run.
              Its settings are kept and it resumes when Privacy First is turned off.
            </p>
          )}
        </div>
        <button
          onClick={() => onUpdate(agent.slug, "enabled", !agent.enabled)}
          className={`h-6 w-11 shrink-0 rounded-full transition-colors ${agent.enabled ? "bg-brand-teal" : "bg-brand-light-gray-1"}`}
          role="switch"
          aria-checked={agent.enabled}
          title={agent.enabled ? "Enabled" : "Disabled"}
        >
          <span className={`block h-5 w-5 rounded-full bg-surface shadow transition-transform ${agent.enabled ? "translate-x-5" : "translate-x-0.5"}`} />
        </button>
      </div>

      {/* Settings grid: model + cadence side by side */}
      <div className="grid gap-4 px-5 py-4 md:grid-cols-2">
        <div>
          <label className="mb-1 block font-body text-xs font-medium text-brand-gray">Model</label>
          <select
            value={agent.model_id}
            onChange={(e) => onUpdate(agent.slug, "model_id", e.target.value)}
            className="w-full rounded border border-brand-light-gray-1 bg-surface px-3 py-1.5 text-sm text-brand-dark-gray focus:border-brand-teal"
          >
            {groupModels(modelOptions).map((group) => (
              <optgroup key={group.provider} label={group.provider}>
                {group.models.map((m) => {
                  const { locked, suffix } = optionState(m, agent.model_id, localOnly);
                  return (
                    <option key={m.id} value={m.id} disabled={locked}>
                      {optionLabel(m)}{suffix}
                    </option>
                  );
                })}
              </optgroup>
            ))}
          </select>
          {hasLockedModels && (
            <p className="mt-1 font-body text-[10px] text-brand-mid-gray">
              Grayed-out models need an API key for their provider (see the Connections tab)
            </p>
          )}
        </div>

        {intervalDefault !== undefined && (
          <div>
            <label className="mb-1 block font-body text-xs font-medium text-brand-gray">
              {intervalDriven ? "Cycle Interval" : "Cooldown Between Runs"}
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={5}
                max={300}
                value={agent.interval_seconds ?? intervalDefault}
                onChange={(e) => {
                  const val = parseInt(e.target.value, 10);
                  if (!isNaN(val)) onDraftChange(agent.slug, "interval_seconds", val);
                }}
                onBlur={(e) => {
                  const val = Math.max(5, Math.min(300, parseInt(e.target.value, 10) || intervalDefault));
                  onUpdate(agent.slug, "interval_seconds", val);
                }}
                className="w-20 rounded border border-brand-light-gray-1 bg-surface px-2.5 py-1.5 text-center font-mono text-sm text-brand-dark-gray focus:border-brand-teal"
              />
              <span className="font-body text-xs text-brand-mid-gray">seconds</span>
            </div>
            <p className="mt-1 font-body text-[10px] text-brand-mid-gray">
              {intervalDriven
                ? "How often this agent analyzes new transcript (5-300s)"
                : "Minimum time between runs; triggered by new insights (5-300s)"}
            </p>
          </div>
        )}
      </div>

      {/* Knowledge sources (for db-backed agents) */}
      {agent.agent_type === "db" && (
        <div className="border-t border-brand-light-gray-1/70 px-5 py-4">
          <div className="mb-1.5 flex items-baseline justify-between">
            <label className="block font-body text-xs font-medium text-brand-gray">Knowledge Sources</label>
            {agent.knowledge_source_ids.split(",").some((s) => s.trim()) && (
              <button
                type="button"
                onClick={() => onUpdate(agent.slug, "knowledge_source_ids", "")}
                className="font-body text-[10px] text-brand-mid-gray transition-colors hover:text-brand-teal"
              >
                Clear selection
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {knowledgeSources
              .filter((k) => k.active)
              .map((k) => {
                const selected = agent.knowledge_source_ids.split(",").map((s) => s.trim()).includes(k.id);
                return (
                  <TogglePill
                    key={k.id}
                    label={k.name}
                    selected={selected}
                    onToggle={() => {
                      const current = new Set(agent.knowledge_source_ids.split(",").map((s) => s.trim()).filter(Boolean));
                      if (selected) current.delete(k.id); else current.add(k.id);
                      onUpdate(agent.slug, "knowledge_source_ids", [...current].join(","));
                    }}
                  />
                );
              })}
          </div>
          <p className="mt-1 font-body text-[10px] text-brand-mid-gray">
            The knowledge bases this agent matches opportunities against (manage in Knowledge Sources). With none selected it falls back to the built-in Offerings catalog.
          </p>
        </div>
      )}

      {/* Configurable analysis lenses (for consolidated analyst) */}
      {agent.slug === "consolidated_analyst" && (
        <LensEditor agent={agent} onUpdate={onUpdate} onDraftChange={onDraftChange} />
      )}

      {/* Prompt editor — collapsed by default to keep the page scannable */}
      <div className="border-t border-brand-light-gray-1/70">
        <button
          type="button"
          onClick={() => setPromptOpen((v) => !v)}
          aria-expanded={promptOpen}
          className="flex w-full items-center justify-between px-5 py-3 text-left transition-colors hover:bg-brand-light-gray-2/60"
        >
          <span className="flex items-center gap-2 font-body text-xs font-medium text-brand-gray">
            <svg className={`h-3 w-3 text-brand-mid-gray transition-transform ${promptOpen ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            System Prompt
          </span>
          <span className="font-body text-[10px] text-brand-mid-gray">{promptOpen ? "Hide" : "View / edit"}</span>
        </button>
        {promptOpen && (
          <div className="px-5 pb-5">
            <div className="mb-1 flex justify-end">
              <button
                onClick={() => onResetPrompt(agent.slug)}
                className="font-body text-[10px] text-brand-mid-gray transition-colors hover:text-brand-teal"
              >
                Reset to default
              </button>
            </div>
            <textarea
              value={agent.prompt}
              onChange={(e) => onDraftChange(agent.slug, "prompt", e.target.value)}
              onBlur={(e) => onUpdate(agent.slug, "prompt", e.target.value)}
              rows={12}
              className="w-full resize-y rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-2 font-mono text-xs leading-relaxed text-brand-dark-gray focus:border-brand-teal"
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default function AdminPanel({ onBack, desktopUpdate, initialTab, highlightSince, onboarding, onOnboardingContinue }: AdminPanelProps) {
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [knowledgeSources, setKnowledgeSources] = useState<KnowledgeSource[]>([]);
  const [privacy, setPrivacy] = useState<PrivacyConfig | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<AdminTab>(initialTab ?? "agents");
  // Bumped on credential changes so the onboarding card re-checks readiness.
  const [keysRefresh, setKeysRefresh] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, m, k, p, meta] = await Promise.all([
        api.listAgents(),
        api.listModels(),
        api.listKnowledgeSources(),
        api.getPrivacyConfig(),
        // Version is cosmetic here; never let it fail the whole panel
        api.getAppMeta().catch(() => null),
      ]);
      setAgents(a);
      setModels(m);
      setKnowledgeSources(k);
      setPrivacy(p);
      setVersion(meta?.version ?? null);
    } catch (err) {
      console.error("Failed to load agent configs", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Key changes flip model availability; refresh models without re-entering the loading state
  const refreshModels = useCallback(async () => {
    try {
      setModels(await api.listModels());
    } catch (err) {
      console.error("Failed to refresh models", err);
    }
  }, []);

  // The transcription card's live preview selector edits the Audio Bridge
  // agent's model; refresh agents so its card shows the new value.
  const refreshAgents = useCallback(async () => {
    try {
      setAgents(await api.listAgents());
    } catch (err) {
      console.error("Failed to refresh agents", err);
    }
  }, []);

  const handleUpdate = async (slug: string, field: string, value: string | boolean | number | null) => {
    setSaving(slug);
    try {
      const updated = await api.updateAgent(slug, { [field]: value });
      setAgents((prev) => prev.map((a) => (a.slug === slug ? updated : a)));
    } catch (err) {
      console.error("Update failed", err);
    } finally {
      setSaving(null);
    }
  };

  const handleResetPrompt = async (slug: string) => {
    setSaving(slug);
    try {
      const updated = await api.resetAgentPrompt(slug);
      setAgents((prev) => prev.map((a) => (a.slug === slug ? updated : a)));
    } catch (err) {
      console.error("Reset failed", err);
    } finally {
      setSaving(null);
    }
  };

  const handleDraftChange = (slug: string, field: "prompt" | "interval_seconds" | "lenses", value: string | number) => {
    setAgents((prev) => prev.map((a) => (a.slug === slug ? { ...a, [field]: value } : a)));
  };

  const enabledCount = agents.filter((a) => a.enabled).length;
  const activeTabInfo = TABS.find((t) => t.id === activeTab) || TABS[0];

  return (
    <div className="flex h-full min-w-0 flex-col overflow-x-hidden bg-brand-light-gray-2">
      <header className="border-b border-brand-light-gray-1 bg-surface px-4 pt-3 sm:px-6">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="rounded p-1 text-brand-mid-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-dark-gray" title="Back">
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18" />
            </svg>
          </button>
          <div>
            <div className="flex items-baseline gap-2">
              <h1 className="font-display text-lg font-bold text-brand-dark-gray">Administration</h1>
              {version && (
                <span className="rounded-full bg-brand-light-gray-2 px-2 py-0.5 font-mono text-[11px] font-medium text-brand-gray" title="Application version">
                  v{version}
                </span>
              )}
            </div>
            <p className="font-body text-xs text-brand-mid-gray">{activeTabInfo.hint}</p>
          </div>
        </div>

        {/* Tab bar */}
        <nav className="mt-3 flex flex-wrap gap-1" aria-label="Administration sections">
          {TABS.map((tab) => {
            const active = tab.id === activeTab;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                aria-current={active ? "page" : undefined}
                className={`-mb-px shrink-0 border-b-2 px-2 py-2 font-body text-sm font-medium transition-colors sm:px-4 ${
                  active
                    ? "border-brand-teal text-brand-teal"
                    : "border-transparent text-brand-gray hover:border-brand-light-gray-1 hover:text-brand-dark-gray"
                }`}
              >
                {tab.label}
                {tab.id === "about" && highlightSince && (
                  <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-brand-teal align-middle" title="New release notes" />
                )}
                {tab.id === "agents" && !loading && (
                  <span className={`ml-1.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${active ? "bg-brand-teal/10 text-brand-teal" : "bg-brand-light-gray-2 text-brand-mid-gray"}`}>
                    {enabledCount}/{agents.length}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </header>

      <div className="flex-1 overflow-auto p-4 sm:p-6">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <span className="font-body text-sm text-brand-mid-gray">Loading configuration...</span>
          </div>
        ) : (
          <div className="mx-auto max-w-4xl">
            {/* Global switch shown on every settings tab: it changes which
                models and agents below can run at all. About is read-only, so
                it skips the switch. In first-run onboarding the keys tab
                frames Privacy First inside the setup card instead. */}
            {activeTab !== "about" && !(activeTab === "keys" && onboarding) && (
              <div className="mb-6">
                <PrivacyModeCard config={privacy} onChanged={setPrivacy} />
              </div>
            )}

            {/* All tabs stay mounted so in-progress work (e.g. a diarization
                benchmark recording) survives tab switches. */}
            <div className={activeTab === "agents" ? "space-y-8" : "hidden"}>
              {(() => {
                const assigned = new Set(AGENT_SECTIONS.flatMap((s) => s.slugs));
                const leftover = agents.filter((a) => !assigned.has(a.slug));
                const sections = [
                  ...AGENT_SECTIONS.map((s) => ({
                    ...s,
                    agents: s.slugs
                      .map((slug) => agents.find((a) => a.slug === slug))
                      .filter((a): a is AgentConfig => !!a),
                  })),
                  // Safety net so agents added later never silently disappear
                  { title: "Other", blurb: "Agents not yet assigned to a section.", agents: leftover },
                ];
                return sections.filter((s) => s.agents.length > 0);
              })().map((section) => {
                const sectionAgents = section.agents;
                return (
                  <section key={section.title}>
                    <div className="mb-3">
                      <h2 className="font-display text-sm font-bold uppercase tracking-wider text-brand-mid-gray">{section.title}</h2>
                      <p className="mt-0.5 font-body text-xs text-brand-mid-gray">{section.blurb}</p>
                    </div>
                    <div className="space-y-4">
                      {sectionAgents.map((agent) => (
                        <AgentCard
                          key={agent.slug}
                          agent={agent}
                          models={models}
                          knowledgeSources={knowledgeSources}
                          isSaving={saving === agent.slug}
                          localOnly={privacy?.local_only ?? false}
                          onUpdate={handleUpdate}
                          onResetPrompt={handleResetPrompt}
                          onDraftChange={handleDraftChange}
                        />
                      ))}
                    </div>
                  </section>
                );
              })}
            </div>

            <div className={activeTab === "transcription" ? "space-y-4" : "hidden"}>
              <BatchTranscriptionCard
                models={models}
                localOnly={privacy?.local_only ?? false}
                onLiveModelChanged={refreshAgents}
                gatewayModelId={agents.find((a) => a.slug === "audio_gateway")?.model_id}
              />
              <LocalModelFitCard onIntervalsApplied={refreshAgents} />
              <DiarizationCapabilityCard />
            </div>

            <div className={activeTab === "keys" ? "space-y-4" : "hidden"}>
              {onboarding && (
                <ProviderOnboardingCard
                  privacy={privacy}
                  onPrivacyChanged={setPrivacy}
                  refreshToken={keysRefresh}
                  onContinue={() => onOnboardingContinue?.()}
                />
              )}
              <ApiKeysCard
                onChanged={() => {
                  refreshModels();
                  setKeysRefresh((n) => n + 1);
                }}
              />
              {/* Adding or removing an endpoint changes which models exist, and
                  an on-prem one changes what Privacy First can still run. */}
              <EndpointsCard
                onChanged={() => {
                  refreshModels();
                  void api.getPrivacyConfig().then(setPrivacy).catch(() => {});
                }}
              />
            </div>

            <div className={activeTab === "about" ? "" : "hidden"}>
              <AboutCard version={version} desktopUpdate={desktopUpdate} highlightSince={highlightSince} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
