import { useEffect, useState } from "react";
import * as api from "../services/api";
import { setupReadiness, toReadinessAgentModels, type SetupReadiness } from "../lib/providerOnboarding";

interface WelcomeViewProps {
  hasSessions: boolean;
  onNewSession: () => void;
  onOpenApiKeys: () => void;
}

function CheckIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3} aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  );
}

function StepCard({
  step,
  done,
  title,
  description,
  notice,
  action,
}: {
  step: number;
  done: boolean;
  title: string;
  description: string;
  // Plain-language explanation of why the step is still incomplete even
  // though the user already did something (e.g. saved a mismatched key).
  notice?: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div className="flex items-start gap-4 rounded-xl bg-surface p-5 text-left shadow-sm ring-1 ring-brand-light-gray-1/60">
      <span
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-display text-sm font-bold ${
          done ? "bg-brand-teal text-white" : "bg-brand-light-gray-2 text-brand-gray"
        }`}
        aria-label={done ? `Step ${step} complete` : `Step ${step}`}
      >
        {done ? <CheckIcon /> : step}
      </span>
      <div className="min-w-0 flex-1">
        <h3 className="font-display text-sm font-bold text-brand-dark-gray">{title}</h3>
        <p className="mt-1 font-body text-xs leading-relaxed text-brand-gray">{description}</p>
        {notice && !done && (
          <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-2.5 py-1.5 font-body text-[11px] leading-relaxed text-amber-900">
            {notice}
          </p>
        )}
      </div>
      {action && !done && (
        <button
          type="button"
          onClick={action.onClick}
          className="shrink-0 self-center rounded-lg bg-brand-teal px-3.5 py-2 font-body text-xs font-semibold text-white transition-colors hover:bg-brand-teal/90"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}

// Shown in the content area when no session is selected. For a brand-new
// workspace (no sessions yet) it becomes a first-run checklist driven by real
// setup state and the first session. Once sessions exist it stays a quiet
// empty state.
export default function WelcomeView({ hasSessions, onNewSession, onOpenApiKeys }: WelcomeViewProps) {
  const [readiness, setReadiness] = useState<SetupReadiness | null>(null);
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    if (!hasSessions) {
      // Step 1 completes only when the currently selected transcription and
      // agent configuration can actually run.
      Promise.all([
        api.getPrivacyConfig().catch(() => null),
        api.getTranscriptionReadiness().catch(() => null),
        api.listAgents().catch(() => []),
        api.listModels().catch(() => []),
      ]).then(([p, transcription, agents, models]) => {
        setReadiness(
          setupReadiness({
            localOnly: p?.local_only === true,
            transcription,
            agentModels: toReadinessAgentModels(agents, models),
          })
        );
      });
    }
    api.getAppMeta().then((m) => setVersion(m.version)).catch(() => null);
  }, [hasSessions]);

  const versionFooter = version && (
    <p className="mt-8 text-center font-body text-[11px] text-brand-mid-gray">Backchannel v{version}</p>
  );

  if (hasSessions) {
    return (
      <div className="flex h-full items-center justify-center text-brand-mid-gray">
        <div className="text-center">
          <h2 className="mb-2 font-display text-2xl font-semibold">Welcome to Backchannel</h2>
          <p className="font-body">Select a session from the sidebar or create a new one to get started.</p>
          {versionFooter}
        </div>
      </div>
    );
  }

  const setupReady = readiness?.ready === true;
  const checklistLoaded = readiness !== null;
  const setupNotice =
    checklistLoaded && !setupReady ? readiness.reason : undefined;

  return (
    <div className="flex h-full items-start justify-center overflow-auto bg-brand-light-gray-2 p-6">
      <div className="w-full max-w-2xl py-8">
        <div className="mb-8 text-center">
          <h2 className="font-display text-3xl font-bold text-brand-dark-gray">Welcome to Backchannel</h2>
          <p className="mx-auto mt-3 max-w-xl font-body text-sm leading-relaxed text-brand-gray">
            Backchannel works alongside your meetings: it transcribes the call live with speaker
            attribution, surfaces questions, objections, and opportunities as they happen, and
            writes a briefing you can review, export, or chat with afterwards.
          </p>
        </div>

        <div className="space-y-3">
          <StepCard
            step={1}
            done={checklistLoaded && setupReady}
            title="Choose your AI models"
            description="Built-in local transcription works without a key. Connect Google, OpenAI, or a self-hosted service if you want its models, then choose a model for each enabled agent. Recommended marks a good starting point."
            notice={setupNotice}
            action={{ label: "Open AI settings", onClick: onOpenApiKeys }}
          />
          <StepCard
            step={2}
            done={hasSessions}
            title="Create your first session"
            description="A session holds everything about one meeting: participants, documents, directives, the transcript, and every insight the agents find."
            action={{ label: "New session", onClick: onNewSession }}
          />
          <StepCard
            step={3}
            done={false}
            title="Start the call, or import one"
            description="From the session screen, start live capture (microphone plus optional tab or system audio), or import an existing recording or transcript to run the same analysis after the fact."
          />
        </div>

        <p className="mt-6 text-center font-body text-xs text-brand-mid-gray">
          You can tune agents, models, prompts, and privacy at any time under Administration.
        </p>
        {versionFooter}
      </div>
    </div>
  );
}
