import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("./insightTypes.ts", import.meta.url), "utf8");

test("asked is a built-in type with the operator label", () => {
  assert.match(src, /asked:\s*\{\s*label:\s*"You asked",\s*plural:\s*"Asked",\s*color:\s*"#475569"\s*\}/);
});

test("asked sorts before every agent type", () => {
  const order = src.match(/BUILTIN_TYPE_ORDER\s*=\s*\[([^\]]*)\]/);
  assert.ok(order, "BUILTIN_TYPE_ORDER not found");
  const first = order[1].split(",")[0].trim();
  assert.equal(first, '"asked"');
});

test("asked does not reuse an agent type color", () => {
  const agentColors = ["#0d9488", "#f59e0b", "#7c3aed", "#10b981", "#e2231a"];
  assert.ok(!agentColors.includes("#475569"));
});

// Runtime checks: Node strips the type annotations, so the module loads as-is.
const load = () => import("./insightTypes.ts");

const row = (id, item_type, lens_label, extra = {}) => ({
  id,
  item_type,
  lens_label,
  question: `Row ${id}`,
  created_at: "2026-09-01T20:00:00Z",
  dismissed: false,
  ...extra,
});

test("signal groups never borrow a row's section badge as the group label", async () => {
  const { typeGroupLabel } = await load();
  // The screenshot case (ALP goal, 2026-09-01): one current signal per section,
  // where a tie resolves to the first badge seen - "Action Cue" - and seventy
  // retired rows that are mostly action cues. Both groups rendered as
  // "ACTION CUE" and the Insights tab showed the same heading twice.
  const current = [
    row("s-1", "signal", "Action Cue"),
    row("s-2", "signal", "Opportunity"),
    row("s-3", "signal", "Next Question"),
    row("s-4", "signal", "Risk"),
    row("s-5", "signal", "Signal"),
  ];
  const history = Array.from({ length: 70 }, (_, i) =>
    row(`h-${i}`, "signal_history", i % 5 === 0 ? "Risk" : "Action Cue"),
  );

  const currentLabel = typeGroupLabel("signal", current);
  const historyLabel = typeGroupLabel("signal_history", history);

  assert.equal(currentLabel, "Strategic Signals");
  assert.equal(historyLabel, "Signal History");
  assert.notEqual(currentLabel, historyLabel);
  assert.doesNotMatch(currentLabel, /Action Cue/);
  assert.doesNotMatch(historyLabel, /Action Cue/);
});

test("signal cards keep their section badge even though the group does not", async () => {
  const { typeLabel } = await load();
  assert.equal(typeLabel("signal", "Risk"), "Risk");
  assert.equal(typeLabel("signal_history", "Action Cue"), "Action Cue");
  // Without a badge the built-in singular still applies.
  assert.equal(typeLabel("signal", ""), "Strategic Signal");
  assert.equal(typeLabel("signal_history", undefined), "Past Signal");
});

test("the live chips keep the short plurals the docs name", async () => {
  // QuestionList builds its chips from the plural; docs/agents.md documents
  // them as Strategic and History, so the fuller group headings must not
  // leak into the live call strip.
  const { BUILTIN_TYPE_META } = await load();
  assert.equal(BUILTIN_TYPE_META.signal.plural, "Strategic");
  assert.equal(BUILTIN_TYPE_META.signal_history.plural, "History");
});

test("lens-produced groups still take their heading from the producing lens", async () => {
  const { typeGroupLabel } = await load();
  // A renamed analyst lens surfaces its new heading everywhere; the built-in
  // plural is only the fallback for rows that carry no lens_label.
  const observations = [
    row("o-1", "observation", "Notable Facts"),
    row("o-2", "observation", "Notable Facts"),
    row("o-3", "observation", ""),
  ];
  assert.equal(typeGroupLabel("observation", observations), "Notable Facts");
  assert.equal(typeGroupLabel("observation", [row("o-4", "observation", "")]), "Observations");
  assert.equal(typeGroupLabel("custom_lens", []), "Custom Lens");
});

test("visible refinement notes omit bookkeeping-only revisions", async () => {
  const { visibleEnrichmentNotes } = await load();

  assert.deepEqual(
    visibleEnrichmentNotes("Merged with another insight\nAdjusted\nCustomer confirmed timing"),
    ["Customer confirmed timing"],
  );
  assert.deepEqual(
    visibleEnrichmentNotes("Adjusted: clarified the owner"),
    ["Adjusted: clarified the owner"],
  );
  assert.deepEqual(visibleEnrichmentNotes(undefined), []);
});
