import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("./ModelChip.tsx", import.meta.url), "utf8");

test("reuses the shared picker rules instead of reimplementing them", () => {
  assert.match(src, /from "\.\.\/\.\.\/lib\/modelOptions"/);
  assert.match(src, /groupModels/);
  assert.match(src, /optionState/);
});

test("locked options are not selectable and state a reason", () => {
  assert.match(src, /disabled=\{[^}]*locked/);
  assert.match(src, /suffix/);
});

test("the popover closes on Escape", () => {
  assert.match(src, /Escape/);
});

test("the chip is a real button for keyboard users", () => {
  assert.match(src, /<button[\s\S]*type="button"/);
});
