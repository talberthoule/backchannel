import assert from "node:assert/strict";
import test from "node:test";
import { createInstance } from "i18next";
import i18n, { changeLanguage, ENABLED_LOCALES, SUPPORTED_LOCALES } from "./index.ts";

const fakeDocument = { documentElement: { lang: "" } };
globalThis.document = fakeDocument;

test("every supplied and validated catalog is active", () => {
  assert.deepEqual([...ENABLED_LOCALES], [...SUPPORTED_LOCALES]);
});

test("empty and missing target values render the English source", async () => {
  const fallback = createInstance();
  await fallback.init({
    resources: {
      en: {
        translation: {
          empty: "English source",
          missing: "English fallback",
        },
      },
      de: {
        translation: {
          empty: "",
        },
      },
    },
    lng: "de",
    fallbackLng: "en",
    returnEmptyString: false,
    initAsync: false,
  });

  assert.equal(fallback.t("empty"), "English source");
  assert.equal(fallback.t("missing"), "English fallback");
});

test("language changes update the document language immediately", async () => {
  await i18n.changeLanguage("de");
  assert.equal(fakeDocument.documentElement.lang, "de");
  assert.notEqual(i18n.t("navigation.language"), "Language");
  await i18n.changeLanguage("en");
  assert.equal(fakeDocument.documentElement.lang, "en");
});

test("the public switcher accepts every enabled locale", async () => {
  for (const locale of ENABLED_LOCALES) {
    await changeLanguage(locale);
    assert.equal(i18n.language, locale);
  }
  await changeLanguage("en");
});
