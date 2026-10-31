import assert from "node:assert/strict";
import test from "node:test";
import {
  LANGUAGE_STORAGE_KEY,
  mapBrowserLanguage,
  persistLanguage,
  readStoredLanguage,
  resolveInitialLanguage,
  setDocumentLanguage,
  SUPPORTED_LOCALES,
} from "./language.ts";

const ALL = SUPPORTED_LOCALES;

test("supported regional browser variants map to a deliberate app locale", () => {
  assert.equal(mapBrowserLanguage("en-GB"), "en");
  assert.equal(mapBrowserLanguage("de-AT"), "de");
  assert.equal(mapBrowserLanguage("fr-CA"), "fr");
  assert.equal(mapBrowserLanguage("pt-BR"), "pt-BR");
  assert.equal(mapBrowserLanguage("pt"), "pt-BR");
  assert.equal(mapBrowserLanguage("pt-PT"), null);
  assert.equal(mapBrowserLanguage("zh-Hans-CN"), "zh-CN");
  assert.equal(mapBrowserLanguage("zh-TW"), null);
  assert.equal(mapBrowserLanguage("xx-YY"), null);
});

test("browser detection falls back to English while only English is enabled", () => {
  assert.equal(
    resolveInitialLanguage({ saved: null, browserLanguages: ["fr-FR", "en-US"], enabled: ["en"] }),
    "en",
  );
  assert.equal(
    resolveInitialLanguage({ saved: null, browserLanguages: ["fr-FR"], enabled: ["en", "fr"] }),
    "fr",
  );
});

test("an enabled saved preference wins over the browser language", () => {
  assert.equal(
    resolveInitialLanguage({ saved: "de", browserLanguages: ["fr-FR"], enabled: ["en", "de", "fr"] }),
    "de",
  );
  assert.equal(
    resolveInitialLanguage({ saved: "de", browserLanguages: ["fr-FR"], enabled: ["en", "fr"] }),
    "fr",
  );
});

test("unsupported, invalid, and unavailable storage never prevents startup", () => {
  assert.equal(readStoredLanguage(null), null);
  assert.equal(readStoredLanguage({ getItem: () => { throw new Error("blocked"); }, setItem: () => {} }), null);
  assert.equal(readStoredLanguage({ getItem: () => "xx", setItem: () => {} }), null);
  assert.doesNotThrow(() => persistLanguage("en", { getItem: () => null, setItem: () => { throw new Error("blocked"); } }));
});

test("explicit selections persist under the namespaced storage key", () => {
  let stored = null;
  const storage = {
    getItem: (key) => key === LANGUAGE_STORAGE_KEY ? stored : null,
    setItem: (key, value) => {
      assert.equal(key, LANGUAGE_STORAGE_KEY);
      stored = value;
    },
  };
  persistLanguage("en", storage);
  assert.equal(stored, "en");
  assert.equal(readStoredLanguage(storage), "en");
});

test("every declared locale has an enabled state and a valid code", () => {
  assert.equal(new Set(ALL).size, 14);
  assert.ok(ALL.includes("pt-BR"));
  assert.ok(!ALL.includes("pt"));
});

test("document language can be updated without a renderer", () => {
  const document = { documentElement: { lang: "" } };
  setDocumentLanguageWith("fr-CA", document);
  assert.equal(document.documentElement.lang, "fr-CA");
});

function setDocumentLanguageWith(language, fakeDocument) {
  const original = globalThis.document;
  globalThis.document = fakeDocument;
  try {
    setDocumentLanguage(language);
  } finally {
    globalThis.document = original;
  }
}
