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
