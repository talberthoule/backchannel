import assert from "node:assert/strict";
import test from "node:test";

const load = () => import("./postProcessingSummary.ts");

test("labels the final analysis pass and anchors against the session total", async () => {
  const { formatPostProcessingSummary } = await load();
  assert.equal(
    formatPostProcessingSummary({
      insights_saved: 3,
      synthesizer_ops: 7,
      opportunity_ops: 0,
      session_insight_total: 23,
    }),
    "Final analysis pass: 3 new insights, 7 insights updated - 23 insights total for this session",
  );
});

test("includes offering matches and singular forms", async () => {
  const { formatPostProcessingSummary } = await load();
  assert.equal(
    formatPostProcessingSummary({
      insights_saved: 1,
      synthesizer_ops: 1,
      opportunity_ops: 1,
      session_insight_total: 1,
    }),
    "Final analysis pass: 1 new insight, 1 insight updated, 1 offering match - 1 insight total for this session",
  );
});

test("shows the total even when the final pass changed nothing", async () => {
  const { formatPostProcessingSummary } = await load();
  assert.equal(
    formatPostProcessingSummary({
      insights_saved: 0,
      synthesizer_ops: 0,
      opportunity_ops: 0,
      session_insight_total: 23,
    }),
    "Final analysis pass: no changes - 23 insights total for this session",
  );
});

test("older backends without a total still get pass counters, no anchor", async () => {
  const { formatPostProcessingSummary } = await load();
  assert.equal(
    formatPostProcessingSummary({ insights_saved: 2, synthesizer_ops: 0 }),
    "Final analysis pass: 2 new insights",
  );
});

test("stays silent with no details or nothing to report", async () => {
  const { formatPostProcessingSummary } = await load();
  assert.equal(formatPostProcessingSummary(undefined), null);
  assert.equal(formatPostProcessingSummary({}), null);
  assert.equal(
    formatPostProcessingSummary({ insights_saved: 0, synthesizer_ops: 0 }),
    null,
  );
});

test("a saved drain summary survives a mid-drain disconnect", async () => {
  const { parseSavedDrainSummary, formatPostProcessingSummary } = await import(
    "./postProcessingSummary.ts"
  );

  const saved = parseSavedDrainSummary(
    JSON.stringify({
      message: "Post-processing complete, but 1 analysis stage failed (call briefing)",
      insights_saved: 3,
      synthesizer_ops: 0,
      opportunity_ops: 0,
      stage_errors: [{ stage: "call_briefing", detail: "hit its output limit" }],
    }),
  );

  assert.ok(saved);
  assert.match(saved.message, /call briefing/);
  assert.equal(saved.stage_errors.length, 1);
  // And it still renders through the same formatter as the live details.
  assert.ok(formatPostProcessingSummary(saved));
});

test("an unusable saved drain summary is ignored rather than thrown", async () => {
  const { parseSavedDrainSummary } = await import("./postProcessingSummary.ts");

  // Sessions predating the column, and anything malformed, must not break the view.
  assert.equal(parseSavedDrainSummary(""), null);
  assert.equal(parseSavedDrainSummary(undefined), null);
  assert.equal(parseSavedDrainSummary("not json"), null);
  assert.equal(parseSavedDrainSummary("[1,2]"), null);
  assert.equal(parseSavedDrainSummary("null"), null);
});
