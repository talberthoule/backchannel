import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source = readFileSync(new URL("./SpeakerNameMapper.tsx", import.meta.url), "utf8");

test("speaker rows do not crush detected names into a fixed-width badge group", () => {
  assert.doesNotMatch(source, /w-36 shrink-0/);
  assert.match(source, /break-words/);
  assert.match(source, /title=\{speaker\.name\}/);
});

test("mapped names use a keyboard-accessible edit control", () => {
  assert.match(source, /aria-label=\{`Edit mapped name for \$\{speaker\.name\}`\}/);
  assert.match(source, /aria-pressed=\{speaker\.display_name_enabled\}/);
});

test("enhancement explains and confirms speaker-aware revalidation", () => {
  assert.match(source, /Correct speaker names and roles first\./);
  assert.match(source, /Briefing and every Insight/);
  assert.match(source, /confirm\(/);
  assert.match(source, /onRefreshSynthesis/);
});
