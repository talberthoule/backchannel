// Cost-estimate math for the post-call Tokens tab and the Admin -> About
// "Models & pricing" table.
//
// Estimates use standard text-tier rates only: no long-context surcharges,
// no cached-input discounts, and audio-heavy input on token-billed transcribe
// models is priced at the model's listed input rate. Models billed by audio
// duration instead carry a per-minute rate and are priced from recorded
// seconds. Models with no published price of either kind yield null and
// render as "-", never $0.00.
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
  audio_seconds?: number;
}

export type PricingMap = Record<string, ModelPricing | null | undefined>;

// Estimated USD cost for one model's usage, or null when nothing about the
// row can be priced (unknown model, or rates the provider does not publish).
//
// Token cost and duration cost are summed rather than treated as alternatives:
// a model billed only by the minute has null token rates, and pricing it on
// tokens alone dropped it from the report entirely (ALP-300).
export function estimateCostUsd(
  pricing: ModelPricing | null | undefined,
  inputTokens: number,
  outputTokens: number,
  thinkingTokens = 0,
  audioSeconds = 0,
): number | null {
  if (!pricing) return null;
  let total: number | null = null;
  if (pricing.input_per_million !== null && pricing.output_per_million !== null) {
    total =
      (inputTokens / 1_000_000) * pricing.input_per_million +
      ((outputTokens + thinkingTokens) / 1_000_000) * pricing.output_per_million;
  }
  if (pricing.per_minute !== null && pricing.per_minute !== undefined) {
    total = (total ?? 0) + (audioSeconds / 60) * pricing.per_minute;
  }
  return total;
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
      row.audio_seconds ?? 0,
    );
    if (cost === null) continue;
    total = (total ?? 0) + cost;
  }
  return total;
}

// Audio duration for the usage tables: minutes are the billing unit, but a
// short clip reading "0.0 min" looks like nothing was spent.
export function formatAudioDuration(seconds: number): string {
  if (seconds <= 0) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${(seconds / 60).toFixed(1)} min`;
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

// Per-minute rates are small enough that two decimals would round the live
// gateway's $0.017 to $0.02, so they get their own precision.
export function formatPerMinuteRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "-";
  return `$${rate.toFixed(3)} / min`;
}
