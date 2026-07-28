import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const componentPath = fileURLToPath(new URL("./AgentActivityPanel.tsx", import.meta.url));
const outputDir = await mkdtemp(join(tmpdir(), "agent-activity-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  stdin: {
    contents: `
      export { activityEmptyMessage, isRunningLate } from "./AgentActivityPanel.tsx";
    `,
    resolveDir: dirname(componentPath),
    sourcefile: "agent-activity-test-entry.tsx",
    loader: "tsx",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: outputPath,
});

const { activityEmptyMessage, isRunningLate } =
  createRequire(import.meta.url)(outputPath);

after(async () => {
  await rm(outputDir, { recursive: true, force: true });
});

const waitingAgent = {
  slug: "consolidated_analyst",
  name: "Consolidated Analyst",
  trigger: "interval",
  state: "waiting",
  enabled: true,
  blocked_reason: "",
  remedy: "",
  interval_seconds: 40,
  last_run_started_at: null,
  last_run_ms: null,
  next_due_at: "2026-07-28T12:00:30.000Z",
  last_outcome: null,
  last_error: null,
  counts: { runs: 0, insights: 0, deduped: 0, errors: 0 },
};

test("healthy silence names the real cadence and first due time", () => {
  const message = activityEmptyMessage(
    {
      agents: [waitingAgent],
      call: { degraded: false },
    },
    false,
    Date.parse("2026-07-28T12:00:00.000Z"),
  );

  assert.equal(
    message,
    "Agents are listening. Consolidated Analyst checks every 40s - first insights expected in about 30s.",
  );
});

test("an interval agent is late only after a full interval overdue", () => {
  const due = Date.parse(waitingAgent.next_due_at);
  assert.equal(isRunningLate(waitingAgent, due + 39_000), false);
  assert.equal(isRunningLate(waitingAgent, due + 41_000), true);
});
