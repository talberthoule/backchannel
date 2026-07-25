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
    const existing = groups.find((g) => g.provider === model.provider);
    if (existing) existing.models.push(model);
    else groups.push({ provider: model.provider, models: [model] });
  }
  return groups;
}

/** A model runs locally when it is a bundled ONNX model or served on-prem. */
export function runsLocally(model: ModelInfo): boolean {
  return model.runs_locally ?? model.provider === "Local";
}

export function optionLabel(model: ModelInfo): string {
  // An endpoint model's id ("endpoint:<slug>:<name>") is plumbing; its group
  // heading already names the server it comes from.
  return model.endpoint_id ? model.name : `${model.name} (${model.id})`;
}

/**
 * Whether an option should be selectable, and why not when it is not.
 * The currently stored model is never locked, so a picker always shows what
 * an agent is actually set to.
 */
export function optionState(model: ModelInfo, currentId: string | undefined, localOnly: boolean) {
  const cloudBlocked = localOnly && !runsLocally(model);
  const keyLocked = model.key_available === false;
  return {
    locked: (keyLocked || cloudBlocked) && model.id !== currentId,
    suffix: cloudBlocked
      ? " - cloud model, off in Privacy First"
      : keyLocked
        ? " - add API key to enable"
        : "",
  };
}
