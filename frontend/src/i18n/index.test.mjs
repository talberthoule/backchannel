import assert from "node:assert/strict";
import test from "node:test";
import i18n, { changeLanguage, ENABLED_LOCALES } from "./index.ts";

const fakeDocument = { documentElement: { lang: "" } };
globalThis.document = fakeDocument;

test("English is the only active locale in the staging release", () => {
  assert.deepEqual([...ENABLED_LOCALES], ["en"]);
});

test("empty and missing target values render the English source", async () => {
  await i18n.changeLanguage("de");
  assert.equal(i18n.t("navigation.language"), "Language");
  assert.equal(i18n.t("navigation.thisKeyDoesNotExist"), "navigation.thisKeyDoesNotExist");
  await i18n.changeLanguage("en");
});

test("language changes update the document language immediately", async () => {
  await i18n.changeLanguage("de");
  assert.equal(fakeDocument.documentElement.lang, "de");
  await i18n.changeLanguage("en");
  assert.equal(fakeDocument.documentElement.lang, "en");
});

test("the public switcher refuses a locale that is not enabled", async () => {
  await changeLanguage("de");
  assert.equal(i18n.language, "en");
});
