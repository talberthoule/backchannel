import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("the stop wait is bounded by silence, not by total drain length", () => {
  const hook = readFileSync(new URL("./useWebSocket.ts", import.meta.url), "utf8");

  // Every message rearms the deadline, so a drain that legitimately runs for
  // minutes survives as long as progress or heartbeats keep arriving (ALP-171).
  assert.match(hook, /armStopDeadline\(\);\s*\n\s*if \(msg\.type === "status"/);
  // The old failure mode: one fixed timer armed at send time and never reset.
  assert.doesNotMatch(hook, /setTimeout\(\(\) => resolveStop\(false\), 180000\)/);
});

test("a silent backend is reported as still processing, not as a lost connection", async () => {
  const hook = readFileSync(new URL("./useWebSocket.ts", import.meta.url), "utf8");

  // Silence and a closed socket are different answers: only the latter means
  // the recording may actually be gone.
  assert.match(hook, /resolveStop\("still_processing"\)/);
  assert.match(hook, /resolveStop\("disconnected"\)/);
  assert.match(hook, /export type StopOutcome =/);
});

test("the end-call caller distinguishes the three stop outcomes", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");

  assert.match(app, /stopOutcome === "completed"/);
  // Silence hands off to a poller instead of the unconfirmed/resume path.
  assert.match(app, /stopOutcome === "still_processing"/);
  assert.match(app, /pollSessionCompletion\(activeSessionId\)/);
  assert.match(app, /backgroundPostProcessing/);
});
