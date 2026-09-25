import assert from "node:assert/strict";
import test from "node:test";

const load = () => import("./transcriptionLanguage.ts");
const names = { de: "German", ja: "Japanese" };
const name = (code) => names[code] ?? code;

const v2 = { name: "Parakeet TDT 0.6B (Local)", languages: ["en"] };
const v3 = { name: "Parakeet v3", languages: ["en", "de", "fr"] };
const whisper = { name: "Whisper Base (Local)" };

test("multilingual or provider-decided models never warn", async () => {
  const { languageMismatch } = await load();
  assert.equal(languageMismatch(whisper, "ja", name), null);
  assert.equal(languageMismatch(undefined, "ja", name), null);
});

test("a set language the model does not cover warns by name", async () => {
  const { languageMismatch } = await load();
  assert.match(languageMismatch(v2, "de", name), /does not transcribe German/);
  assert.match(languageMismatch(v3, "ja", name), /does not transcribe Japanese/);
  assert.equal(languageMismatch(v3, "de", name), null);
});

test("auto flags only English-only models", async () => {
  const { languageMismatch } = await load();
  assert.match(languageMismatch(v2, "auto", name), /English only/);
  assert.equal(languageMismatch(v3, "auto", name), null);
  assert.equal(languageMismatch(v2, "en", name), null);
});
