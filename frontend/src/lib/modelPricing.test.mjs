import assert from "node:assert/strict";
import test from "node:test";

const load = () => import("./modelPricing.ts");

const price = (input, output, extra = {}) => ({
  input_per_million: input,
  output_per_million: output,
  cached_input_per_million: null,
  audio_input_per_million: null,
  per_minute: null,
  audio_output_per_million: null,
  ...extra,
});

const usage = (input_tokens, output_tokens, extra = {}) => ({ input_tokens, output_tokens, ...extra });

// Floating-point sums of per-million products land a hair off; compare to
// the cent, which is the only precision the UI shows.
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} != ${expected}`);

test("estimates cost from input and output rates per 1M tokens", async () => {
  const { estimateCostUsd } = await load();
  // 500k in at $2.50/1M + 100k out at $15.00/1M = 1.25 + 1.50
  assert.equal(estimateCostUsd(price(2.5, 15.0), usage(500_000, 100_000)), 2.75);
});

test("thinking tokens are priced at the output rate", async () => {
  const { estimateCostUsd } = await load();
  // 500k in at $2.50/1M + (100k out + 100k thinking) at $15.00/1M = 1.25 + 3.00
  assert.equal(estimateCostUsd(price(2.5, 15.0), usage(500_000, 100_000, { thinking_tokens: 100_000 })), 4.25);
  // Omitting the slice keeps the two-part estimate.
  assert.equal(estimateCostUsd(price(2.5, 15.0), usage(500_000, 100_000)), 2.75);
});

test("cached input tokens are priced at the cached rate, the rest at the text rate", async () => {
  const { estimateCostUsd } = await load();
  const pricing = price(0.75, 3.75, { cached_input_per_million: 0.075 });
  // 1M input of which 800k cached: 200k at 0.75 + 800k at 0.075 = 0.15 + 0.06; 10k out at 3.75 = 0.0375
  close(estimateCostUsd(pricing, usage(1_000_000, 10_000, { cached_input_tokens: 800_000 })), 0.2475);
});

test("audio input tokens are priced at the audio rate", async () => {
  const { estimateCostUsd } = await load();
  // The live gateway: nearly all input is audio at 4x the text rate.
  const pricing = price(0.75, 4.5, { audio_input_per_million: 3.0, audio_output_per_million: 12.0 });
  // 1M input, 960k audio: 40k at 0.75 (0.03) + 960k at 3.00 (2.88); 10k output all audio at 12.00 (0.12)
  close(
    estimateCostUsd(pricing, usage(1_000_000, 10_000, { audio_input_tokens: 960_000, audio_output_tokens: 10_000 })),
    3.03,
  );
});

test("a slice without a published rate prices at the plain rate", async () => {
  const { estimateCostUsd } = await load();
  // gemini-3.5-flash-lite publishes one input rate for every modality.
  const pricing = price(0.3, 2.5, { cached_input_per_million: 0.03 });
  close(
    estimateCostUsd(pricing, usage(1_000_000, 0, { audio_input_tokens: 900_000 })),
    estimateCostUsd(pricing, usage(1_000_000, 0)),
  );
  // Same for audio output when only the text output rate exists.
  close(
    estimateCostUsd(pricing, usage(0, 100_000, { audio_output_tokens: 100_000 })),
    estimateCostUsd(pricing, usage(0, 100_000)),
  );
});

test("slices never exceed the side they belong to", async () => {
  const { estimateCostUsd } = await load();
  const pricing = price(1.0, 2.0, { cached_input_per_million: 0.1, audio_input_per_million: 4.0, audio_output_per_million: 8.0 });
  // Cached and audio both claim the whole input: cached wins the tokens and
  // the audio slice is clamped to what is left (nothing), so the text slice
  // can never go negative.
  close(
    estimateCostUsd(pricing, usage(1_000_000, 1_000, { cached_input_tokens: 2_000_000, audio_input_tokens: 2_000_000, audio_output_tokens: 5_000 })),
    0.1 + 0.008,
  );
});

test("session total prices each row's thinking tokens", async () => {
  const { estimateSessionCostUsd } = await load();
  const pricing = { "gemini-flash": price(1.5, 7.5) };
  const rows = [{ model_id: "gemini-flash", input_tokens: 1_000_000, output_tokens: 100_000, thinking_tokens: 200_000 }];
  // 1.50 + (300k at $7.50/1M) = 1.50 + 2.25
  assert.equal(estimateSessionCostUsd(rows, pricing), 3.75);
});

test("session total prices each row's cached and audio slices", async () => {
  const { estimateSessionCostUsd } = await load();
  const pricing = {
    "gemini-2.5-flash": price(0.3, 2.5, { cached_input_per_million: 0.03, audio_input_per_million: 1.0 }),
  };
  const rows = [
    // batch transcription: 1M input, 990k of it audio
    { model_id: "gemini-2.5-flash", input_tokens: 1_000_000, output_tokens: 0, audio_input_tokens: 990_000 },
  ];
  // 10k at 0.30 (0.003) + 990k at 1.00 (0.99)
  close(estimateSessionCostUsd(rows, pricing), 0.993);
});

test("duration-billed models price from recorded seconds", async () => {
  const { estimateCostUsd } = await load();
  const pricing = price(null, null, { per_minute: 0.017 });
  // Token rates are null, so a token-shaped payload alone is unpriced ...
  assert.equal(estimateCostUsd(pricing, usage(1000, 10)), null);
  // ... and 120 seconds of audio is two minutes at the per-minute rate.
  close(estimateCostUsd(pricing, usage(0, 0, { audio_seconds: 120 })), 0.034);
});

test("free local models cost exactly zero", async () => {
  const { estimateCostUsd } = await load();
  assert.equal(estimateCostUsd(price(0, 0), usage(123_456, 7_890)), 0);
});

test("missing or unpriced entries yield null, not zero", async () => {
  const { estimateCostUsd } = await load();
  assert.equal(estimateCostUsd(undefined, usage(1000, 1000)), null);
  assert.equal(estimateCostUsd(null, usage(1000, 1000)), null);
  assert.equal(estimateCostUsd(price(null, null), usage(1000, 1000)), null);
});

test("session total sums priced rows and skips unpriced ones", async () => {
  const { estimateSessionCostUsd } = await load();
  const pricing = {
    "gpt-5.4": price(2.5, 15.0),
    "local-whisper-base": price(0, 0),
    "gpt-realtime-whisper": null,
  };
  const rows = [
    { model_id: "gpt-5.4", input_tokens: 1_000_000, output_tokens: 100_000 },
    { model_id: "local-whisper-base", input_tokens: 50_000, output_tokens: 5_000 },
    { model_id: "gpt-realtime-whisper", input_tokens: 999_999, output_tokens: 0 },
    { model_id: "unknown-model", input_tokens: 10, output_tokens: 10 },
  ];
  assert.equal(estimateSessionCostUsd(rows, pricing), 4.0);
});

test("session total is null when nothing could be priced", async () => {
  const { estimateSessionCostUsd } = await load();
  assert.equal(estimateSessionCostUsd([], {}), null);
  assert.equal(
    estimateSessionCostUsd([{ model_id: "mystery", input_tokens: 5, output_tokens: 5 }], {}),
    null,
  );
});

test("formats costs: dash for null, $0.00 for free, floor for sub-cent", async () => {
  const { formatEstimatedCost } = await load();
  assert.equal(formatEstimatedCost(null), "-");
  assert.equal(formatEstimatedCost(0), "$0.00");
  assert.equal(formatEstimatedCost(0.0004), "<$0.01");
  assert.equal(formatEstimatedCost(0.01), "$0.01");
  assert.equal(formatEstimatedCost(2.75), "$2.75");
  assert.equal(formatEstimatedCost(2.756), "$2.76");
});

test("formats per-1M rates with a dash for unpublished values", async () => {
  const { formatRate } = await load();
  assert.equal(formatRate(null), "-");
  assert.equal(formatRate(undefined), "-");
  assert.equal(formatRate(0), "$0.00");
  assert.equal(formatRate(1.5), "$1.50");
});

test("formats per-minute rates at three decimals", async () => {
  const { formatPerMinuteRate } = await load();
  assert.equal(formatPerMinuteRate(null), "-");
  assert.equal(formatPerMinuteRate(0.017), "$0.017 / min");
});

test("formats audio duration in seconds below a minute, minutes above", async () => {
  const { formatAudioDuration } = await load();
  assert.equal(formatAudioDuration(0), "-");
  assert.equal(formatAudioDuration(42.4), "42s");
  assert.equal(formatAudioDuration(150), "2.5 min");
});
