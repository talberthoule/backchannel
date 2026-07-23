import { useCallback, useEffect, useState } from "react";
import type { PrivacyConfig } from "../types";
import * as api from "../services/api";
import {
  onboardingStage,
  setupReadiness,
  toReadinessAgentModels,
  type ReadinessTranscription,
  type SetupReadiness,
} from "../lib/providerOnboarding";

interface ProviderOnboardingCardProps {
  privacy: PrivacyConfig | null;
  onPrivacyChanged: (config: PrivacyConfig) => void;
  // Bumped by the parent whenever a credential changes so readiness re-checks.
  refreshToken: number;
  onContinue: () => void;
}

// Contextual first-run setup state shown above the API Keys card only when
// the screen was entered from the welcome checklist's "Add API key" action.
// Frames the one decision that matters -- one cloud provider key or Privacy
// First -- and offers a continue action once the currently selected
// configuration is actually usable.
export default function ProviderOnboardingCard({
  privacy,
  onPrivacyChanged,
  refreshToken,
  onContinue,
}: ProviderOnboardingCardProps) {
  const [anyKeySaved, setAnyKeySaved] = useState(false);
  const [readiness, setReadiness] = useState<SetupReadiness | null>(null);
  const [privacyBusy, setPrivacyBusy] = useState(false);

  const localOnly = privacy?.local_only === true;

  const check = useCallback(async () => {
    try {
      const [credentials, transcription, agents, models] = await Promise.all([
        api.listCredentials(),
        api.getTranscriptionReadiness().catch(() => null),
        api.listAgents(),
        api.listModels(),
      ]);
      setAnyKeySaved(credentials.some((c) => c.configured || c.env_fallback));
      setReadiness(
        setupReadiness({
          localOnly,
          transcription: transcription as ReadinessTranscription | null,
          agentModels: toReadinessAgentModels(agents, models),
        })
      );
    } catch (err) {
      console.error("Failed to check setup readiness", err);
    }
  }, [localOnly]);

  useEffect(() => {
    check();
  }, [check, refreshToken]);

  const handlePrivacyFirst = async () => {
    setPrivacyBusy(true);
    try {
      onPrivacyChanged(await api.updatePrivacyConfig(true));
    } catch (err) {
      console.error("Failed to enable Privacy First", err);
    } finally {
      setPrivacyBusy(false);
    }
  };

  const stage = readiness ? onboardingStage({ anyKeySaved, readiness }) : "choose";
  const disabledImpact = privacy?.impact.disabled ?? [];

  return (
    <div className="rounded-xl border border-brand-teal/30 bg-surface p-5 shadow-sm">
      <p className="font-body text-[10px] font-semibold uppercase tracking-wider text-brand-teal">
        First-time setup
      </p>
      <h3 className="mt-0.5 font-display text-base font-bold text-brand-dark-gray">
        Choose how Backchannel runs
      </h3>
      <p className="mt-1 font-body text-xs leading-relaxed text-brand-gray">
        You need one working setup path -- not a key for every provider. Pick
        one of these and you are done:
      </p>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-brand-teal/40 bg-brand-teal/5 p-3.5">
          <h4 className="font-display text-sm font-bold text-brand-dark-gray">
            Cloud AI
          </h4>
          <p className="mt-1.5 font-body text-xs leading-relaxed text-brand-gray">
            Add an API key from Google (Gemini) or OpenAI -- one key from
            either provider is enough. Use the <strong>Get a key</strong> link
            below, paste the key into that provider's field, and click
            <strong> Save</strong> -- saving runs a connection test
            automatically.
          </p>
        </div>

        <div className="rounded-lg border border-brand-light-gray-1 p-3.5">
          <h4 className="font-display text-sm font-bold text-brand-dark-gray">
            Privacy First (no cloud)
          </h4>
          <p className="mt-1.5 font-body text-xs leading-relaxed text-brand-gray">
            No API key and no audio leaves this machine: transcription runs on
            local models instead.
            {disabledImpact.length > 0 && (
              <>
                {" "}Trade-off: {disabledImpact.map((i) => i.feature).join(", ")}{" "}
                stay off until a cloud key is added.
              </>
            )}
          </p>
          {localOnly ? (
            <p className="mt-2 font-body text-xs font-medium text-brand-teal">
              Privacy First is on.
            </p>
          ) : (
            <button
              type="button"
              onClick={handlePrivacyFirst}
              disabled={privacyBusy}
              className="mt-2 rounded border border-brand-light-gray-1 px-3 py-1.5 font-body text-xs font-medium text-brand-dark-gray transition-colors hover:border-brand-teal hover:text-brand-teal disabled:opacity-40"
            >
              Turn on Privacy First
            </button>
          )}
        </div>
      </div>

      {stage === "partial" && readiness && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2.5">
          <p className="font-body text-xs font-semibold text-amber-900">
            Almost there -- your key is saved, but the current setup cannot run yet.
          </p>
          <p className="mt-1 font-body text-xs leading-relaxed text-amber-900">
            {readiness.reason}
          </p>
        </div>
      )}

      {stage === "ready" && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-brand-teal/40 bg-brand-teal/5 px-3.5 py-2.5">
          <p className="font-body text-xs font-medium text-brand-dark-gray">
            {localOnly
              ? "Privacy First is on -- local transcription is ready to go."
              : "Setup complete -- your provider key covers the selected transcription and analysis models."}
          </p>
          <button
            type="button"
            onClick={onContinue}
            className="rounded-lg bg-brand-teal px-3.5 py-2 font-body text-xs font-semibold text-white transition-colors hover:bg-brand-teal/90"
          >
            Continue to first session
          </button>
        </div>
      )}
    </div>
  );
}
