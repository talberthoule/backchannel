import type { ModelInfo } from "../types";

export function resolveStoredAskModel(
  stored: string | null,
  models: Pick<ModelInfo, "id" | "supports_text">[],
): string {
  return stored && models.some((model) => model.id === stored && model.supports_text)
    ? stored
    : "";
}
