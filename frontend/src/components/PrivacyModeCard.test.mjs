import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("./PrivacyModeCard.tsx", import.meta.url), "utf8");

// The Privacy First review panel painted a fixed cream ground in both themes
// while its item titles and details used the semantic brand tokens, which go
// light in dark mode. The result was light text on a light panel: the feature
// names were unreadable exactly when someone was deciding whether to turn the
// switch on. A fixed ground has to declare its dark counterpart.
const GROUND = /\bbg-(?:amber|red|emerald|green|blue|yellow)-(?:50|100)\b/;

function classNames(text) {
  return [...text.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)]
    .map((match) => match[1] ?? match[2]);
}

test("every fixed light ground in this card declares a dark counterpart", () => {
  const offenders = classNames(source)
    .filter((value) => GROUND.test(value) && !/\bdark:bg-/.test(value));
  assert.deepEqual(offenders, [], "a light ground with no dark variant");
});

test("the review panel keeps readable text on both themes", () => {
  const panel = source.slice(source.indexOf("Review what changes before enabling"));
  // The headings are fixed amber, so they need the dark pairing spelled out.
  assert.match(source, /text-amber-900 dark:text-amber-200/);
  // The status glyphs, likewise.
  assert.match(source, /text-red-500 dark:text-red-400/);
  assert.match(source, /text-emerald-600 dark:text-emerald-400/);
  // And the item titles stay on the semantic tokens, which now sit on a
  // ground that flips with them.
  assert.match(panel, /text-brand-dark-gray/);
});
