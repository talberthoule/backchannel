// Pure setup-readiness logic behind the first-run provider onboarding
// (welcome checklist step 1 and the contextual API Keys setup card). Kept
// free of service imports so node --test can exercise it directly.

export interface ReadinessTranscription {
  ready: boolean;
  model_id: string;
  provider: string;
  reason: string;
}

// One enabled agent joined to its selected model's registry entry. keyAvailable
// mirrors ModelInfo.key_available with absence treated as available.
export interface ReadinessAgentModel {
  agentName: string;
  enabled: boolean;
  modelId: string;
  provider: string;
  keyAvailable: boolean;
}

export interface SetupReadiness {
  ready: boolean;
  // Plain-language explanation of the first blocking gap; empty when ready.
  reason: string;
}

// A workspace is ready only when the currently selected transcription and
// agent configuration can actually run -- not merely when some provider key
// exists. An OpenAI-only key with the seeded Gemini defaults must come back
// not-ready with an explanation instead of falsely reporting readiness.
export function setupReadiness(input: {
  localOnly: boolean;
  transcription: ReadinessTranscription | null;
  agentModels: ReadinessAgentModel[];
}): SetupReadiness {
  if (input.localOnly) return { ready: true, reason: "" };

  const t = input.transcription;
  if (!t) return { ready: false, reason: "Checking transcription setup..." };
  if (!t.ready) {
    const reason =
      t.reason.trim() ||
      `The selected transcription model (${t.model_id}) needs a working ` +
        `${t.provider} API key. Add that key below, or switch the ` +
        `transcription model, or turn on Privacy First to use local models.`;
    return { ready: false, reason };
  }

  const blocked = input.agentModels.filter(
    (a) => a.enabled && a.provider !== "Local" && !a.keyAvailable
  );
  if (blocked.length > 0) {
    const names = blocked
      .slice(0, 3)
      .map((a) => `${a.agentName} (${a.provider})`)
      .join(", ");
    const more = blocked.length > 3 ? ` and ${blocked.length - 3} more` : "";
    return {
      ready: false,
      reason:
        `Transcription is ready, but the selected models for ${names}${more} ` +
        `have no working API key. Add that provider's key, or pick different ` +
        `models under Administration -> Agents.`,
    };
  }

  return { ready: true, reason: "" };
}

// Which contextual state the onboarding setup card is in. "choose" shows the
// two-path decision, "partial" surfaces the mismatch explanation for a saved
// but insufficient key, "ready" offers the continue action.
export type OnboardingStage = "choose" | "partial" | "ready";

export function onboardingStage(input: {
  anyKeySaved: boolean;
  readiness: SetupReadiness;
}): OnboardingStage {
  if (input.readiness.ready) return "ready";
  return input.anyKeySaved ? "partial" : "choose";
}
