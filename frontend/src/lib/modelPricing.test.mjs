import assert from "node:assert/strict";
import test from "node:test";

const load = () => import("./modelPricing.ts");

const price = (input, output) => ({
  input_per_million: input,
  output_per_million: output,
  cached_input_per_million: null,
  audio_input_per_million: null,
});

test("estimates cost from input and output rates per 1M tokens", async () => {
  const { estimateCostUsd } = await load();
  // 500k in at $2.50/1M + 100k out at $15.00/1M = 1.25 + 1.50
  assert.equal(estimateCostUsd(price(2.5, 15.0), 500_000, 100_000), 2.75);
});

test("thinking tokens are priced at the output rate", async () => {
  const { estimateCostUsd } = await load();
  // 500k in at $2.50/1M + (100k out + 100k thinking) at $15.00/1M = 1.25 + 3.00
  assert.equal(estimateCostUsd(price(2.5, 15.0), 500_000, 100_000, 100_000), 4.25);
  // Omitting the argument keeps the pre-existing two-part estimate.
  assert.equal(estimateCostUsd(price(2.5, 15.0), 500_000, 100_000), 2.75);
});

test("session total prices each row's thinking tokens", async () => {
  const { estimateSessionCostUsd } = await load();
  const pricing = { "gemini-flash": price(1.5, 7.5) };
  const rows = [{ model_id: "gemini-flash", input_tokens: 1_000_000, output_tokens: 100_000, thinking_tokens: 200_000 }];
  // 1.50 + (300k at $7.50/1M) = 1.50 + 2.25
  assert.equal(estimateSessionCostUsd(rows, pricing), 3.75);
});

test("free local models cost exactly zero", async () => {
  const { estimateCostUsd } = await load();
  assert.equal(estimateCostUsd(price(0, 0), 123_456, 7_890), 0);
});

test("missing or unpriced entries yield null, not zero", async () => {
  const { estimateCostUsd } = await load();
  assert.equal(estimateCostUsd(undefined, 1000, 1000), null);
  assert.equal(estimateCostUsd(null, 1000, 1000), null);
  assert.equal(estimateCostUsd(price(null, null), 1000, 1000), null);
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
