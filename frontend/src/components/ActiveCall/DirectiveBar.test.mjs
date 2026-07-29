import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("./DirectiveBar.tsx", import.meta.url), "utf8");

test("the bar defaults to chat mode", () => {
  assert.match(src, /useState<Mode>\(\s*(\(\)\s*=>\s*)?[^)]*"chat"/);
});

test("the input is always open, not behind an expand button", () => {
  assert.ok(!/setExpanded/.test(src), "expand/collapse state should be gone");
  assert.match(src, /<input/);
});

test("mode persists across sessions", () => {
  assert.match(src, /localStorage/);
});

test("both modes are reachable", () => {
  assert.match(src, /Directive/);
  assert.match(src, /Chat/);
});

test("the model chip is rendered", () => {
  assert.match(src, /<ModelChip/);
});
