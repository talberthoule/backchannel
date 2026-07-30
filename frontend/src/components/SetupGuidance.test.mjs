import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (name) =>
  readFileSync(new URL(name, import.meta.url), "utf8");

test("first-run guidance explains explicit selection without demanding Gemini", () => {
  const copy = read("./WelcomeView.tsx") + read("./ProviderOnboardingCard.tsx");

  assert.doesNotMatch(copy, /free Google \(Gemini\) key covers/i);
  assert.doesNotMatch(copy, /one of these and you are done/i);
  assert.match(copy, /built-in local transcription/i);
  assert.match(copy, /Recommended/);
  assert.match(copy, /does not change your model selections/i);
});
