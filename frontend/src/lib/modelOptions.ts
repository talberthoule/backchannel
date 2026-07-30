import type { ModelInfo } from "../types";

/** Shared rendering rules for every model <select> in the app.
 *
 * Kept in one place because the agent picker, the transcription picker, and
 * the chat picker must agree on which models Privacy First allows: with
 * self-hosted endpoints, "local" is no longer the same as "provider is Local".
 */

export interface ModelGroup {
  provider: string;
  models: ModelInfo[];
}

/** Group models under their provider, preserving the order they arrive in. */
export function groupModels(models: ModelInfo[]): ModelGroup[] {
  const groups: ModelGroup[] = [];
  for (const model of models) {
    const provider = runsLocally(model) ? "Local" : model.provider;
    const existing = groups.find((g) => g.provider === provider);
    if (existing) existing.models.push(model);
    else groups.push({ provider, models: [model] });
  }
  return groups;
}

/** A model runs locally when it is a bundled ONNX model or served on-prem. */
export function runsLocally(model: ModelInfo): boolean {
  return model.runs_locally ?? model.provider === "Local";
}

export function recommendationFor(model: ModelInfo, role?: string) {
  if (!role) return undefined;
  return model.recommendations?.find(
    (recommendation) => recommendation.role === role && recommendation.recommended
  );
}

export function optionLabel(model: ModelInfo, role?: string): string {
  // An endpoint model's id ("endpoint:<slug>:<name>") is plumbing; its group
  // is Local for an on-prem server, so keep the endpoint name in the row.
  const label = model.endpoint_id
    ? `${model.name} (${model.provider})`
    : `${model.name} (${model.id})`;
  return recommendationFor(model, role) ? `${label} - Recommended` : label;
}

/**
 * Whether an option should be selectable, and why not when it is not.
 * The currently stored model is never locked, so a picker always shows what
 * an agent is actually set to.
 */
export function optionState(model: ModelInfo, currentId: string | undefined, localOnly: boolean) {
  const cloudBlocked = localOnly && !runsLocally(model);
  const keyLocked = model.key_available === false;
  // An endpoint model is only "cloud" when its server is not on your machine or
  // LAN, so name that reason instead of implying the model itself is hosted.
  const cloudSuffix = model.endpoint_id
    ? " - endpoint is not on your machine/LAN, off in Privacy First"
    : " - cloud model, off in Privacy First";
  return {
    locked: (keyLocked || cloudBlocked) && model.id !== currentId,
    suffix: cloudBlocked
      ? cloudSuffix
      : keyLocked
        ? " - add API key to enable"
        : "",
  };
}
