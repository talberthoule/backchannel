import assert from "node:assert/strict";
import test from "node:test";

const load = () => import("./askModelSelection.ts");
const models = [
  { id: "gpt-5.6-terra", supports_text: true },
  { id: "gpt-realtime-whisper", supports_text: false },
];

test("a valid stored Live Ask choice is preserved", async () => {
  const { resolveStoredAskModel } = await load();
  assert.equal(resolveStoredAskModel("gpt-5.6-terra", models), "gpt-5.6-terra");
});

test("missing, removed, or non-text choices stay explicitly unselected", async () => {
  const { resolveStoredAskModel } = await load();
  assert.equal(resolveStoredAskModel(null, models), "");
  assert.equal(resolveStoredAskModel("removed", models), "");
  assert.equal(resolveStoredAskModel("gpt-realtime-whisper", models), "");
});
