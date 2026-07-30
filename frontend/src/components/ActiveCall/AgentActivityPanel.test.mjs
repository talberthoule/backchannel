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
      export { activityEmptyMessage, isRunningLate, summarizeAgents } from "./AgentActivityPanel.tsx";
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

const { activityEmptyMessage, isRunningLate, summarizeAgents } =
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

test("an event-driven agent is never marked running late", () => {
  const eventAgent = {
    ...waitingAgent,
    slug: "synthesizer",
    name: "Synthesizer",
    trigger: "event",
    interval_seconds: 75,
  };
  const due = Date.parse(eventAgent.next_due_at);

  assert.equal(isRunningLate(eventAgent, due + 151_000), false);
});

test("an expected meeting-type block preserves the healthy cadence message", () => {
  const message = activityEmptyMessage(
    {
      agents: [
        waitingAgent,
        {
          ...waitingAgent,
          slug: "opportunity_specialist",
          name: "Opportunity Specialist",
          trigger: "event",
          state: "blocked",
          blocked_reason: "meeting_type",
          interval_seconds: 55,
          next_due_at: null,
        },
      ],
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

test("blocked chip counts non-privacy blocked agents only (ALP-193)", () => {
  const now = Date.parse("2026-07-28T12:00:00.000Z");
  const stats = summarizeAgents(
    [
      waitingAgent,
      {
        ...waitingAgent,
        slug: "opportunity_specialist",
        state: "blocked",
        blocked_reason: "meeting_type",
        next_due_at: null,
      },
      {
        ...waitingAgent,
        slug: "objection_handler",
        state: "blocked",
        blocked_reason: "privacy_first",
        next_due_at: null,
      },
      {
        ...waitingAgent,
        slug: "synthesizer",
        state: "off",
        blocked_reason: "disabled",
        next_due_at: null,
      },
    ],
    now,
  );

  assert.equal(stats.blocked, 1);
});

test("no-model blocks get their own setup count", () => {
  const stats = summarizeAgents(
    [
      {
        ...waitingAgent,
        state: "blocked",
        blocked_reason: "no_model",
        remedy: "Choose a model under Administration -> Agents.",
        next_due_at: null,
      },
      {
        ...waitingAgent,
        slug: "opportunity_specialist",
        state: "blocked",
        blocked_reason: "meeting_type",
        next_due_at: null,
      },
    ],
    Date.parse("2026-07-28T12:00:00.000Z"),
  );

  assert.equal(stats.needSetup, 1);
  assert.equal(stats.blocked, 1);
});

test("failed chip reflects current failing state, not cumulative errors (ALP-193)", () => {
  const now = Date.parse("2026-07-28T12:00:00.000Z");
  const recovered = {
    ...waitingAgent,
    slug: "objection_handler",
    counts: { runs: 12, insights: 3, deduped: 0, errors: 2 },
  };
  const failing = {
    ...waitingAgent,
    slug: "strategic_signals",
    state: "failing",
    counts: { runs: 4, insights: 1, deduped: 0, errors: 1 },
  };

  assert.equal(summarizeAgents([recovered], now).failed, 0);
  assert.equal(summarizeAgents([recovered, failing], now).failed, 1);
});
