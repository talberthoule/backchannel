import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("./QuestionCard.tsx", import.meta.url), "utf8");

test("live_chat has an operator-facing agent label", () => {
  assert.match(src, /live_chat:\s*"You asked"/);
});

test("make directive is offered only on asked cards", () => {
  assert.match(src, /onMakeDirective/);
  assert.match(src, /itemType === "asked"/);
});
