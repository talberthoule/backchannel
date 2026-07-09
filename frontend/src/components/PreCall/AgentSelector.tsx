import { useCallback, useEffect, useState } from "react";
import type { SessionAgent } from "../../types";
import * as api from "../../services/api";

const TYPE_COLORS: Record<string, string> = {
  audio: "#0d9488",
  text: "#7c3aed",
  meta: "#f59e0b",
  db: "#10b981",
};

interface AgentSelectorProps {
  sessionId: string;
}

export default function AgentSelector({ sessionId }: AgentSelectorProps) {
  const [agents, setAgents] = useState<SessionAgent[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const a = await api.listSessionAgents(sessionId);
      setAgents(a);
    } catch (err) {
      console.error("Failed to load session agents", err);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => { load(); }, [load]);

  const handleToggle = async (slug: string, enabled: boolean) => {
    // Optimistic update
    setAgents((prev) => prev.map((a) => (a.slug === slug ? { ...a, enabled, is_override: true } : a)));

    // Build full override list from current state
    const updated = agents.map((a) => ({
      agent_slug: a.slug,
      enabled: a.slug === slug ? enabled : a.enabled,
    }));

    try {
      const result = await api.setSessionAgents(sessionId, updated);
      setAgents(result);
    } catch (err) {
      console.error("Failed to update agent override", err);
      load(); // revert on error
    }
  };

  const handleResetAll = async () => {
    try {
      const result = await api.setSessionAgents(sessionId, []);
      setAgents(result);
    } catch (err) {
      console.error("Failed to reset overrides", err);
    }
  };

  if (loading) {
    return <p className="text-xs text-brand-mid-gray">Loading agents...</p>;
  }

  const hasOverrides = agents.some((a) => a.is_override);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="font-body text-xs text-brand-mid-gray">
          Choose which agents participate in this call
        </p>
        {hasOverrides && (
          <button onClick={handleResetAll} className="font-body text-[10px] text-brand-mid-gray hover:text-brand-teal transition-colors">
            Reset to defaults
          </button>
        )}
      </div>

      {agents.map((agent) => (
        <div
          key={agent.slug}
          className="flex items-center justify-between rounded-lg border border-brand-light-gray-1 bg-surface px-3 py-2.5 shadow-sm"
        >
          <div className="flex items-center gap-2.5">
            <span
              className="inline-flex rounded-full px-1.5 py-0.5 text-[9px] font-medium text-white shrink-0"
              style={{ backgroundColor: TYPE_COLORS[agent.agent_type] || "#666" }}
            >
              {agent.agent_type}
            </span>
            <div>
              <span className="font-body text-sm font-medium text-brand-dark-gray">{agent.name}</span>
              {agent.is_override && (
                <span className="ml-1.5 text-[9px] text-brand-mid-gray">(custom)</span>
              )}
              <p className="font-body text-[11px] text-brand-mid-gray leading-snug mt-0.5">{agent.description}</p>
            </div>
          </div>
          <button
            onClick={() => handleToggle(agent.slug, !agent.enabled)}
            className={`h-5 w-9 rounded-full transition-colors shrink-0 ml-3 ${agent.enabled ? "bg-brand-teal" : "bg-brand-light-gray-1"}`}
          >
            <span className={`block h-4 w-4 rounded-full bg-surface shadow transition-transform ${agent.enabled ? "translate-x-4" : "translate-x-0.5"}`} />
          </button>
        </div>
      ))}
    </div>
  );
}
