import assert from "node:assert/strict";
import test from "node:test";

const load = () => import("./modelOptions.ts");

test("on-prem endpoint models are grouped under Local and keep endpoint identity", async () => {
  const { groupModels, optionLabel } = await load();
  const models = [
    { id: "gemini", name: "Flash", provider: "Google", runs_locally: false },
    {
      id: "endpoint:studio:qwen",
      name: "Qwen",
      provider: "LM Studio",
      endpoint_id: "studio",
      runs_locally: true,
    },
  ];

  const groups = groupModels(models);

  assert.deepEqual(groups.map((group) => group.provider), ["Google", "Local"]);
  assert.equal(optionLabel(models[1]), "Qwen (LM Studio)");
});

test("recommended option text is driven by structured role metadata", async () => {
  const { optionLabel, recommendationFor } = await load();
  const model = {
    id: "gpt-5.6-terra",
    name: "GPT-5.6 Terra",
    provider: "OpenAI",
    recommendations: [
      {
        role: "consolidated_analyst",
        provider: "openai",
        recommended: true,
        source: "provider_default",
      },
    ],
  };

  assert.ok(recommendationFor(model, "consolidated_analyst"));
  assert.equal(
    optionLabel(model, "consolidated_analyst"),
    "GPT-5.6 Terra (gpt-5.6-terra) - Recommended",
  );
  assert.equal(optionLabel(model, "objection_handler"), "GPT-5.6 Terra (gpt-5.6-terra)");
});
