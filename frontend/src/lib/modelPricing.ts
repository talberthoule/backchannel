// Cost-estimate math for the post-call Tokens tab and the Admin -> About
// "Models & pricing" table.
//
// Estimates use standard text-tier rates only: no long-context surcharges,
// no cached-input discounts, and audio-heavy input (live gateway, transcribe
// models) is priced at the model's listed input rate. Models without a
// published per-token price yield null and render as "-", never $0.00.
//
// Thinking tokens bill at the output rate. Omitting them understated a
// measured session by about a third, so they are priced here explicitly.

import type { ModelPricing } from "../types";

// A row of the token-usage by-model breakdown (subset of TokenUsageBreakdown).
export interface TokenCostRow {
  model_id: string;
  input_tokens: number;
  output_tokens: number;
  thinking_tokens?: number;
}

export type PricingMap = Record<string, ModelPricing | null | undefined>;

// Estimated USD cost for one model's usage, or null when the model has no
// pricing entry (unknown model or unpublished per-token rates).
export function estimateCostUsd(
  pricing: ModelPricing | null | undefined,
  inputTokens: number,
  outputTokens: number,
  thinkingTokens = 0,
): number | null {
  if (!pricing) return null;
  if (pricing.input_per_million === null || pricing.output_per_million === null) return null;
  return (
    (inputTokens / 1_000_000) * pricing.input_per_million +
    ((outputTokens + thinkingTokens) / 1_000_000) * pricing.output_per_million
  );
}

// Session total across the by-model rows. Rows without pricing are excluded;
// null when no row could be priced (so the UI shows "-" instead of $0.00).
export function estimateSessionCostUsd(rows: TokenCostRow[], pricing: PricingMap): number | null {
  let total: number | null = null;
  for (const row of rows) {
    const cost = estimateCostUsd(
      pricing[row.model_id],
      row.input_tokens,
      row.output_tokens,
      row.thinking_tokens ?? 0,
    );
    if (cost === null) continue;
    total = (total ?? 0) + cost;
  }
  return total;
}

// Display rules: null -> "-"; zero -> "$0.00"; positive-but-under-a-cent ->
// "<$0.01"; otherwise two decimals.
export function formatEstimatedCost(cost: number | null): string {
  if (cost === null) return "-";
  if (cost === 0) return "$0.00";
  if (cost < 0.01) return "<$0.01";
  return `$${cost.toFixed(2)}`;
}

// Price-per-1M display for the About pricing table ("-" when unpublished).
export function formatRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "-";
  return `$${rate.toFixed(2)}`;
}
