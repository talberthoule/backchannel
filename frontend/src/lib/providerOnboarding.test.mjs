import assert from "node:assert/strict";
import test from "node:test";

const load = () => import("./providerOnboarding.ts");

// The seeded defaults: Gemini batch transcription plus Gemini text agents.
const geminiTranscription = (ready, reason = "") => ({
  ready,
  model_id: "gemini-2.5-flash",
  provider: "Google",
  reason,
});

const geminiAgents = (keyAvailable) => [
  { agentName: "Consolidated Analyst", enabled: true, provider: "Google", keyAvailable },
  { agentName: "Objection Handler", enabled: true, provider: "Google", keyAvailable },
];

test("an OpenAI-only key with the seeded Gemini defaults is not ready and explains why", async () => {
  const { setupReadiness } = await load();
  // Backend transcription readiness fails because the Gemini batch model has
  // no Google key; the OpenAI credential alone must not flip readiness.
  const result = setupReadiness({
    localOnly: false,
    transcription: geminiTranscription(false),
    agentModels: geminiAgents(false),
  });
  assert.equal(result.ready, false);
  assert.match(result.reason, /Google API key/);
  assert.match(result.reason, /Privacy First|transcription model/);
});

test("a backend-provided readiness reason is passed through verbatim", async () => {
  const { setupReadiness } = await load();
  const result = setupReadiness({
    localOnly: false,
    transcription: geminiTranscription(false, "Gemini transcription needs a Google API key."),
    agentModels: geminiAgents(false),
  });
  assert.equal(result.ready, false);
  assert.equal(result.reason, "Gemini transcription needs a Google API key.");
});

test("ready transcription with keyless enabled agent models stays not ready and names the agents", async () => {
  const { setupReadiness } = await load();
  const result = setupReadiness({
    localOnly: false,
    transcription: { ready: true, model_id: "local-whisper", provider: "Local", reason: "" },
    agentModels: geminiAgents(false),
  });
  assert.equal(result.ready, false);
  assert.match(result.reason, /Consolidated Analyst \(Google\)/);
});

test("disabled and local agent models never block readiness", async () => {
  const { setupReadiness } = await load();
  const result = setupReadiness({
    localOnly: false,
    transcription: geminiTranscription(true),
    agentModels: [
      { agentName: "Off Agent", enabled: false, provider: "OpenAI", keyAvailable: false },
      { agentName: "Local Agent", enabled: true, provider: "Local", keyAvailable: false },
    ],
  });
  assert.equal(result.ready, true);
  assert.equal(result.reason, "");
});

test("agent/model join treats registry gaps as non-blocking", async () => {
  const { toReadinessAgentModels } = await load();
  const result = toReadinessAgentModels(
    [
      { name: "Analyst", enabled: true, model_id: "gemini-2.5-flash" },
      { name: "Ghost", enabled: true, model_id: "not-in-registry" },
    ],
    [{ id: "gemini-2.5-flash", provider: "Google", key_available: false }]
  );
  assert.deepEqual(result, [
    { agentName: "Analyst", enabled: true, provider: "Google", keyAvailable: false },
    { agentName: "Ghost", enabled: true, provider: "", keyAvailable: true },
  ]);
});

test("Privacy First local mode is ready regardless of credentials", async () => {
  const { setupReadiness } = await load();
  const result = setupReadiness({
    localOnly: true,
    transcription: null,
    agentModels: geminiAgents(false),
  });
  assert.equal(result.ready, true);
});

// Contextual onboarding card state: no key -> the two-path choice; a saved
// but insufficient key -> the mismatch explanation; a usable setup -> the
// continue action.
test("onboarding stage walks choose -> partial -> ready", async () => {
  const { setupReadiness, onboardingStage } = await load();

  const noKeys = setupReadiness({
    localOnly: false,
    transcription: geminiTranscription(false),
    agentModels: geminiAgents(false),
  });
  assert.equal(onboardingStage({ anyKeySaved: false, readiness: noKeys }), "choose");

  // OpenAI key saved, Gemini defaults still unusable: partial, never ready.
  assert.equal(onboardingStage({ anyKeySaved: true, readiness: noKeys }), "partial");

  const googleReady = setupReadiness({
    localOnly: false,
    transcription: geminiTranscription(true),
    agentModels: geminiAgents(true),
  });
  assert.equal(onboardingStage({ anyKeySaved: true, readiness: googleReady }), "ready");

  const privacyReady = setupReadiness({ localOnly: true, transcription: null, agentModels: [] });
  assert.equal(onboardingStage({ anyKeySaved: false, readiness: privacyReady }), "ready");
});
