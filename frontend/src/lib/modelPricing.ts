// Cost-estimate math for the post-call Tokens tab, the post-call overview,
// and the Admin -> About "Models & pricing" table.
//
// Estimates use standard paid-tier rates only: no long-context surcharges and
// no cache-storage fees. Within a row, input tokens are priced in three
// slices - cached prompt tokens at the cached-input rate, audio tokens at the
// audio-input rate, and the rest at the text rate - and output tokens in two,
// audio output at the audio-output rate and the rest (plus thinking) at the
// text output rate. A slice whose rate the provider does not publish prices at
// the plain rate for its side. Models billed by audio duration instead carry a
// per-minute rate and are priced from recorded seconds. Models with no
// published price of either kind yield null and render as "-", never $0.00.
//
// Thinking tokens bill at the output rate. Omitting them understated a
// measured session by about a third, so they are priced here explicitly.
//
// The cached and audio input slices are assumed not to overlap. In this app
// they never do: cache hits come from the text agents' repeated prompt
// prefixes, and audio tokens from single-shot transcription requests and the
// live gateway, whose context is not served from the cache. Should a provider
// ever report both on one request, the text slice is clamped at zero rather
// than going negative.

import type { ModelPricing } from "../types";

// One usage row to price: the token-usage API's by_source / by_model shape,
// with every slice beyond input and output optional (older rows and older
// backends omit them, and they read as zero).
export interface TokenCostRow {
  model_id: string;
  input_tokens: number;
  output_tokens: number;
  thinking_tokens?: number;
  audio_seconds?: number;
  cached_input_tokens?: number;
  audio_input_tokens?: number;
  audio_output_tokens?: number;
}

// The counts estimateCostUsd prices; model_id is not needed once the rates
// are looked up.
export type UsageCounts = Omit<TokenCostRow, "model_id">;

export type PricingMap = Record<string, ModelPricing | null | undefined>;

const perMillion = (tokens: number, rate: number) => (tokens / 1_000_000) * rate;

// Estimated USD cost for one model's usage, or null when nothing about the
// row can be priced (unknown model, or rates the provider does not publish).
//
// Token cost and duration cost are summed rather than treated as alternatives:
// a model billed only by the minute has null token rates, and pricing it on
// tokens alone dropped it from the report entirely (ALP-300).
export function estimateCostUsd(
  pricing: ModelPricing | null | undefined,
  usage: UsageCounts,
): number | null {
  if (!pricing) return null;
  const inputTokens = Math.max(0, usage.input_tokens ?? 0);
  const outputTokens = Math.max(0, usage.output_tokens ?? 0);
  const thinkingTokens = Math.max(0, usage.thinking_tokens ?? 0);
  const audioSeconds = Math.max(0, usage.audio_seconds ?? 0);
  // Slices can never exceed the side they belong to, whatever the row says.
  const cachedInput = Math.min(inputTokens, Math.max(0, usage.cached_input_tokens ?? 0));
  const audioInput = Math.min(inputTokens - cachedInput, Math.max(0, usage.audio_input_tokens ?? 0));
  const audioOutput = Math.min(outputTokens, Math.max(0, usage.audio_output_tokens ?? 0));

  let total: number | null = null;
  if (pricing.input_per_million !== null && pricing.output_per_million !== null) {
    const textInput = inputTokens - cachedInput - audioInput;
    const textOutput = outputTokens - audioOutput;
    const cachedRate = pricing.cached_input_per_million ?? pricing.input_per_million;
    const audioInRate = pricing.audio_input_per_million ?? pricing.input_per_million;
    const audioOutRate = pricing.audio_output_per_million ?? pricing.output_per_million;
    total =
      perMillion(textInput, pricing.input_per_million) +
      perMillion(cachedInput, cachedRate) +
      perMillion(audioInput, audioInRate) +
      perMillion(textOutput + thinkingTokens, pricing.output_per_million) +
      perMillion(audioOutput, audioOutRate);
  }
  // Only recorded seconds make a duration-billed row priceable: a token-shaped
  // payload from a model with no token rates stays unknown ("-") rather than
  // reading as free.
  if (pricing.per_minute !== null && pricing.per_minute !== undefined && audioSeconds > 0) {
    total = (total ?? 0) + (audioSeconds / 60) * pricing.per_minute;
  }
  return total;
}

// Session total across the by-model rows. Rows without pricing are excluded;
// null when no row could be priced (so the UI shows "-" instead of $0.00).
export function estimateSessionCostUsd(rows: TokenCostRow[], pricing: PricingMap): number | null {
  let total: number | null = null;
  for (const row of rows) {
    const cost = estimateCostUsd(pricing[row.model_id], row);
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
