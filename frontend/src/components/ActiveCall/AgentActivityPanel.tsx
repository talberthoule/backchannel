import { useEffect, useMemo, useState } from "react";
import type {
  AgentActivityRecord,
  AgentActivitySnapshot,
} from "../../types";

export function isRunningLate(
  agent: AgentActivityRecord,
  now = Date.now(),
): boolean {
  if (
    agent.trigger !== "interval"
    || agent.state !== "waiting"
    || !agent.interval_seconds
    || !agent.next_due_at
  ) return false;
  const due = Date.parse(agent.next_due_at);
  return Number.isFinite(due)
    && now > due + agent.interval_seconds * 1000;
}

function duration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
}

function countdown(at: string | null, now: number): string {
  if (!at) return "-";
  const value = Date.parse(at);
  if (!Number.isFinite(value)) return "-";
  const seconds = Math.ceil((value - now) / 1000);
  return seconds > 0 ? duration(seconds) : "due now";
}

function relativeTime(at: string | null, now: number): string {
  if (!at) return "Never";
  const value = Date.parse(at);
  if (!Number.isFinite(value)) return "Never";
  return `${duration(Math.max(0, Math.floor((now - value) / 1000)))} ago`;
}

export function activityEmptyMessage(
  snapshot: Pick<AgentActivitySnapshot, "agents" | "call"> | null,
  hasInsights: boolean,
  now = Date.now(),
): string | undefined {
  if (
    !snapshot
    || snapshot.call.degraded
    || snapshot.agents.some((agent) =>
      agent.state === "failing"
      || (agent.state === "blocked" && agent.blocked_reason !== "meeting_type")
    )
  ) return undefined;

  const candidates = snapshot.agents.filter((agent) =>
    agent.enabled
    && agent.trigger === "interval"
    && agent.state === "waiting"
    && agent.next_due_at
    && agent.slug !== "strategic_signals"
  );
  const agent = candidates.find((item) => item.slug === "consolidated_analyst")
    || candidates.sort(
      (a, b) => Date.parse(a.next_due_at || "") - Date.parse(b.next_due_at || ""),
    )[0];
  if (!agent?.interval_seconds || !agent.next_due_at) return undefined;

  const next = countdown(agent.next_due_at, now);
  if (!hasInsights && agent.counts.runs === 0) {
    return (
      `Agents are listening. ${agent.name} checks every `
      + `${duration(agent.interval_seconds)} - first insights expected in about ${next}.`
    );
  }
  return (
    `Agents are listening. ${agent.name} checks every `
    + `${duration(agent.interval_seconds)} - next check in ${next}.`
  );
}

function chipTone(agent: AgentActivityRecord, now: number): string {
  if (agent.state === "failing") return "bg-red-100 text-red-700";
  if (agent.state === "blocked" || isRunningLate(agent, now)) {
    return "bg-amber-100 text-amber-800";
  }
  if (agent.state === "running") return "bg-emerald-100 text-emerald-700";
  return "bg-brand-light-gray-2 text-brand-gray";
}

function dotTone(agent: AgentActivityRecord, now: number): string {
  if (agent.state === "failing") return "bg-red-500";
  if (agent.state === "blocked" || isRunningLate(agent, now)) return "bg-amber-500";
  if (agent.state === "running") return "animate-pulse bg-emerald-500";
  return "bg-brand-mid-gray";
}

function nextLabel(agent: AgentActivityRecord, now: number): string {
  if (isRunningLate(agent, now)) return "running late";
  if (agent.trigger === "event") return "event-driven";
  if (agent.trigger === "stream") return agent.state;
  if (agent.trigger === "post_call") return "at call end";
  return `next ${countdown(agent.next_due_at, now)}`;
}

export default function AgentActivityPanel({
  snapshot,
}: {
  snapshot: AgentActivitySnapshot | null;
}) {
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const liveAgents = useMemo(
    () => snapshot?.agents.filter(
      (agent) => agent.trigger !== "post_call" && agent.state !== "off",
    ) || [],
    [snapshot],
  );
  const privacyBlocked = snapshot?.agents.filter(
    (agent) => agent.blocked_reason === "privacy_first",
  ).length || 0;
  const briefingAvailable = snapshot?.agents.some(
    (agent) => agent.trigger === "post_call" && agent.state !== "off",
  );

  return (
    <section className="border-b border-brand-light-gray-1 bg-surface">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls="agent-activity-details"
        className="flex w-full items-center gap-2 overflow-x-auto px-4 py-2 text-left md:px-6"
      >
        <span className="flex-shrink-0 font-body text-[10px] font-semibold uppercase tracking-wide text-brand-mid-gray">
          Agent activity
        </span>
        {!snapshot && (
          <span className="flex-shrink-0 rounded-full bg-brand-light-gray-2 px-2 py-1 font-body text-xs text-brand-mid-gray">
            Connecting...
          </span>
        )}
        {privacyBlocked > 0 && (
          <span className="flex-shrink-0 rounded-full bg-amber-100 px-2 py-1 font-body text-xs font-medium text-amber-800">
            {privacyBlocked} agent{privacyBlocked === 1 ? "" : "s"} off: Privacy First
          </span>
        )}
        {liveAgents.map((agent) => (
          <span
            key={agent.slug}
            className={`flex flex-shrink-0 items-center gap-1.5 rounded-full px-2 py-1 font-body text-xs ${chipTone(agent, now)}`}
          >
            <span className={`h-2 w-2 rounded-full ${dotTone(agent, now)}`} />
            <span>{agent.name}</span>
            {agent.state === "waiting" && (
              <span className="opacity-75">{nextLabel(agent, now)}</span>
            )}
          </span>
        ))}
        {briefingAvailable && (
          <span className="flex flex-shrink-0 items-center gap-1.5 rounded-full bg-brand-light-gray-2 px-2 py-1 font-body text-xs text-brand-gray">
            <span className="h-2 w-2 rounded-full bg-brand-mid-gray" />
            Briefing: at call end
          </span>
        )}
        <span className="ml-auto flex-shrink-0 text-brand-mid-gray" aria-hidden="true">
          {open ? "-" : "+"}
        </span>
      </button>

      {open && snapshot && (
        <div id="agent-activity-details" className="overflow-x-auto border-t border-brand-light-gray-1 px-4 py-3 md:px-6">
          <table className="w-full min-w-[900px] text-left font-body text-xs">
            <thead className="text-[10px] uppercase tracking-wide text-brand-mid-gray">
              <tr>
                <th className="pb-2 pr-3">Agent</th>
                <th className="pb-2 pr-3">State</th>
                <th className="pb-2 pr-3">Why</th>
                <th className="pb-2 pr-3">Last run</th>
                <th className="pb-2 pr-3">Next</th>
                <th className="pb-2 pr-3">Last outcome</th>
                <th className="pb-2">Last failure</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-light-gray-1 text-brand-gray">
              {snapshot.agents.map((agent) => (
                <tr key={agent.slug} className="align-top">
                  <td className="py-2 pr-3 font-semibold text-brand-dark-gray">{agent.name}</td>
                  <td className="py-2 pr-3">{agent.state}</td>
                  <td className="max-w-64 py-2 pr-3">
                    {agent.blocked_reason
                      ? `${agent.blocked_reason.replace(/_/g, " ")}. ${agent.remedy}`
                      : "-"}
                  </td>
                  <td className="py-2 pr-3">
                    {relativeTime(agent.last_run_started_at, now)}
                    {agent.last_run_ms !== null ? ` (${agent.last_run_ms}ms)` : ""}
                  </td>
                  <td className="py-2 pr-3">{nextLabel(agent, now)}</td>
                  <td className="max-w-72 py-2 pr-3">
                    {agent.last_outcome?.detail || "-"}
                  </td>
                  <td className="max-w-72 py-2">
                    {agent.last_error
                      ? `${agent.last_error.detail} ${agent.last_error.remedy}`
                      : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 border-t border-brand-light-gray-1 pt-3 font-body text-xs text-brand-mid-gray">
            Gateway: {snapshot.call.gateway.state}
            {" | "}Transcription: {snapshot.call.transcription.jobs} jobs, {snapshot.call.transcription.failed} failed
            {" | "}Speaker processing: {snapshot.call.diarization.queued} queued, {snapshot.call.diarization.shed} skipped
          </p>
        </div>
      )}
    </section>
  );
}
