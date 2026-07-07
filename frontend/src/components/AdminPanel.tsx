import { useCallback, useEffect, useState } from "react";
import type { AgentConfig, KnowledgeSource, ModelInfo, PrivacyConfig } from "../types";
import * as api from "../services/api";
import DiarizationCapabilityCard from "./DiarizationCapabilityCard";
import BatchTranscriptionCard from "./BatchTranscriptionCard";
import ApiKeysCard from "./ApiKeysCard";
import PrivacyModeCard from "./PrivacyModeCard";

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
  consolidated_analyst: 15,
  objection_handler: 5,
  synthesizer: 30,
  opportunity_specialist: 5,
};

// Grouped by when agents run, not by their internal type: the Principal
// Agent (meta) and Opportunity Specialist (db) react to live insights just
// like the cycle-based analysts, while the briefing trio only runs once a
// session ends. Slug order within a section is the display order.
const AGENT_SECTIONS: { slugs: string[]; title: string; blurb: string }[] = [
  {
    slugs: ["audio_gateway"],
    title: "Listening",
    blurb: "Streams call audio to a silent live listener for instant interim transcription.",
  },
  {
    slugs: ["consolidated_analyst", "objection_handler", "synthesizer", "opportunity_specialist"],
    title: "Live Analysis",
    blurb: "Work the call as it happens: the analysts cycle over the growing transcript, while the Principal Agent and Opportunity Specialist react to each new insight to refine, connect, and match it.",
  },
  {
    slugs: ["brief_meeting_lens", "brief_discovery_lens", "brief_arbiter"],
    title: "Post-Call Briefing",
    blurb: "Run once after a session ends: two independent lenses draft the briefing and the arbiter reconciles them into the final summary.",
  },
];

type TabId = "agents" | "transcription" | "keys";

const TABS: { id: TabId; label: string; hint: string }[] = [
  { id: "agents", label: "Agents", hint: "Models, prompts, and behavior for each analysis agent" },
  { id: "transcription", label: "Transcription & Audio", hint: "Speaker diarization and batch transcription settings" },
  { id: "keys", label: "API Keys", hint: "Provider credentials for Google and OpenAI models" },
];

interface AdminPanelProps {
  onBack: () => void;
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
  onDraftChange: (slug: string, field: "prompt" | "interval_seconds", value: string | number) => void;
}) {
  const [promptOpen, setPromptOpen] = useState(false);
  const badge = TYPE_BADGES[agent.agent_type] || TYPE_BADGES.text;
  const intervalDefault = agent.agent_type === "text" ? INTERVAL_DEFAULTS[agent.slug] ?? 15 : INTERVAL_DEFAULTS[agent.slug];
  const modelOptions = models.filter((m) => (agent.agent_type === "audio" ? m.supports_live_audio : m.supports_text));
  const hasLockedModels = modelOptions.some((m) => m.key_available === false);
  // Privacy First mode sidelines any agent that has no local model to run on
  const blockedByPrivacy = localOnly && !modelOptions.some((m) => m.provider === "Local");

  return (
    <div className={`rounded-xl bg-white shadow-sm ring-1 ring-brand-light-gray-1/60 transition-opacity ${isSaving ? "opacity-70" : ""} ${agent.enabled && !blockedByPrivacy ? "" : "opacity-80"}`}>
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
          <span className={`block h-5 w-5 rounded-full bg-white shadow transition-transform ${agent.enabled ? "translate-x-5" : "translate-x-0.5"}`} />
        </button>
      </div>

      {/* Settings grid: model + cadence side by side */}
      <div className="grid gap-4 px-5 py-4 md:grid-cols-2">
        <div>
          <label className="mb-1 block font-body text-xs font-medium text-brand-gray">Model</label>
          <select
            value={agent.model_id}
            onChange={(e) => onUpdate(agent.slug, "model_id", e.target.value)}
            className="w-full rounded border border-brand-light-gray-1 bg-white px-3 py-1.5 text-sm text-brand-dark-gray outline-none focus:border-brand-teal"
          >
            {modelOptions.map((m) => {
              const cloudBlocked = localOnly && m.provider !== "Local";
              const keyLocked = m.key_available === false;
              const locked = (keyLocked || cloudBlocked) && m.id !== agent.model_id;
              const suffix = cloudBlocked ? " — cloud model, off in Privacy First" : keyLocked ? " — add API key to enable" : "";
              return (
                <option key={m.id} value={m.id} disabled={locked}>
                  {m.name} ({m.id}){suffix}
                </option>
              );
            })}
          </select>
          {hasLockedModels && (
            <p className="mt-1 font-body text-[10px] text-brand-mid-gray">
              Grayed-out models need an API key for their provider (see the API Keys tab)
            </p>
          )}
        </div>

        {intervalDefault !== undefined && (
          <div>
            <label className="mb-1 block font-body text-xs font-medium text-brand-gray">
              {agent.agent_type === "text" ? "Cycle Interval" : "Cooldown Between Runs"}
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
                className="w-20 rounded border border-brand-light-gray-1 bg-white px-2.5 py-1.5 text-center font-mono text-sm text-brand-dark-gray outline-none focus:border-brand-teal"
              />
              <span className="font-body text-xs text-brand-mid-gray">seconds</span>
            </div>
            <p className="mt-1 font-body text-[10px] text-brand-mid-gray">
              {agent.agent_type === "text"
                ? "How often this agent analyzes new transcript (5-300s)"
                : "Minimum time between runs; triggered by new insights (5-300s)"}
            </p>
          </div>
        )}
      </div>

      {/* Knowledge sources (for db-backed agents) */}
      {agent.agent_type === "db" && (
        <div className="border-t border-brand-light-gray-1/70 px-5 py-4">
          <label className="mb-1.5 block font-body text-xs font-medium text-brand-gray">Knowledge Sources</label>
          <div className="flex flex-wrap gap-3">
            {knowledgeSources
              .filter((k) => k.active)
              .map((k) => {
                const selected = agent.knowledge_source_ids.split(",").map((s) => s.trim()).includes(k.id);
                return (
                  <label key={k.id} className="flex cursor-pointer items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => {
                        const current = new Set(agent.knowledge_source_ids.split(",").map((s) => s.trim()).filter(Boolean));
                        if (selected) current.delete(k.id); else current.add(k.id);
                        onUpdate(agent.slug, "knowledge_source_ids", [...current].join(","));
                      }}
                      className="h-3.5 w-3.5 rounded border-brand-light-gray-1 text-brand-teal"
                    />
                    <span className="font-body text-xs text-brand-dark-gray">{k.name}</span>
                  </label>
                );
              })}
          </div>
          <p className="mt-1 font-body text-[10px] text-brand-mid-gray">
            The knowledge bases this agent matches opportunities against (manage in Knowledge Sources). With none selected it falls back to the built-in Offerings catalog.
          </p>
        </div>
      )}

      {/* Sub-types (for consolidated analyst) */}
      {agent.slug === "consolidated_analyst" && (
        <div className="border-t border-brand-light-gray-1/70 px-5 py-4">
          <label className="mb-1.5 block font-body text-xs font-medium text-brand-gray">Active Lenses</label>
          <div className="flex flex-wrap gap-3">
            {["question", "observation", "opportunity", "action_item"].map((t) => {
              const active = agent.sub_types.split(",").map((s) => s.trim()).includes(t);
              const labels: Record<string, string> = { question: "Questions", observation: "Observations", opportunity: "Opportunities", action_item: "Action Items" };
              return (
                <label key={t} className="flex cursor-pointer items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() => {
                      const current = new Set(agent.sub_types.split(",").map((s) => s.trim()).filter(Boolean));
                      if (active) current.delete(t); else current.add(t);
                      onUpdate(agent.slug, "sub_types", [...current].join(","));
                    }}
                    className="h-3.5 w-3.5 rounded border-brand-light-gray-1 text-brand-teal"
                  />
                  <span className="font-body text-xs text-brand-dark-gray">{labels[t]}</span>
                </label>
              );
            })}
          </div>
        </div>
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
              className="w-full resize-y rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 px-3 py-2 font-mono text-xs leading-relaxed text-brand-dark-gray outline-none focus:border-brand-teal"
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default function AdminPanel({ onBack }: AdminPanelProps) {
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [knowledgeSources, setKnowledgeSources] = useState<KnowledgeSource[]>([]);
  const [privacy, setPrivacy] = useState<PrivacyConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("agents");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, m, k, p] = await Promise.all([
        api.listAgents(),
        api.listModels(),
        api.listKnowledgeSources(),
        api.getPrivacyConfig(),
      ]);
      setAgents(a);
      setModels(m);
      setKnowledgeSources(k);
      setPrivacy(p);
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

  const handleDraftChange = (slug: string, field: "prompt" | "interval_seconds", value: string | number) => {
    setAgents((prev) => prev.map((a) => (a.slug === slug ? { ...a, [field]: value } : a)));
  };

  const enabledCount = agents.filter((a) => a.enabled).length;
  const activeTabInfo = TABS.find((t) => t.id === activeTab) || TABS[0];

  return (
    <div className="flex h-full flex-col bg-brand-light-gray-2">
      <header className="border-b border-brand-light-gray-1 bg-white px-6 pt-3">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="rounded p-1 text-brand-mid-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-dark-gray" title="Back">
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18" />
            </svg>
          </button>
          <div>
            <h1 className="font-display text-lg font-bold text-brand-dark-gray">Administration</h1>
            <p className="font-body text-xs text-brand-mid-gray">{activeTabInfo.hint}</p>
          </div>
        </div>

        {/* Tab bar */}
        <nav className="mt-3 flex gap-1" aria-label="Administration sections">
          {TABS.map((tab) => {
            const active = tab.id === activeTab;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                aria-current={active ? "page" : undefined}
                className={`-mb-px border-b-2 px-4 py-2 font-body text-sm font-medium transition-colors ${
                  active
                    ? "border-brand-teal text-brand-teal"
                    : "border-transparent text-brand-gray hover:border-brand-light-gray-1 hover:text-brand-dark-gray"
                }`}
              >
                {tab.label}
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

      <div className="flex-1 overflow-auto p-6">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <span className="font-body text-sm text-brand-mid-gray">Loading configuration...</span>
          </div>
        ) : (
          <div className="mx-auto max-w-4xl">
            {/* Global switch shown on every tab: it changes which models and
                agents below can run at all. */}
            <div className="mb-6">
              <PrivacyModeCard config={privacy} onChanged={setPrivacy} />
            </div>

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
              <BatchTranscriptionCard models={models} localOnly={privacy?.local_only ?? false} onLiveModelChanged={refreshAgents} />
              <DiarizationCapabilityCard />
            </div>

            <div className={activeTab === "keys" ? "space-y-4" : "hidden"}>
              <ApiKeysCard onChanged={refreshModels} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
