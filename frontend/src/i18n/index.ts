import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "../locales/en/translation.json" with { type: "json" };
import de from "../locales/de/translation.json" with { type: "json" };
import fr from "../locales/fr/translation.json" with { type: "json" };
import es from "../locales/es/translation.json" with { type: "json" };
import it from "../locales/it/translation.json" with { type: "json" };
import ptBR from "../locales/pt-BR/translation.json" with { type: "json" };
import zhCN from "../locales/zh-CN/translation.json" with { type: "json" };
import ja from "../locales/ja/translation.json" with { type: "json" };
import ko from "../locales/ko/translation.json" with { type: "json" };
import nl from "../locales/nl/translation.json" with { type: "json" };
import ru from "../locales/ru/translation.json" with { type: "json" };
import pl from "../locales/pl/translation.json" with { type: "json" };
import tr from "../locales/tr/translation.json" with { type: "json" };
import ca from "../locales/ca/translation.json" with { type: "json" };
import {
  ENABLED_LOCALES,
  LANGUAGE_STORAGE_KEY,
  LOCALE_LABELS,
  SUPPORTED_LOCALES,
  getBrowserLanguages,
  persistLanguage,
  readStoredLanguage,
  resolveInitialLanguage,
  setDocumentLanguage,
  type SupportedLocale,
} from "./language.ts";

export {
  ENABLED_LOCALES,
  LANGUAGE_STORAGE_KEY,
  LOCALE_LABELS,
  SUPPORTED_LOCALES,
  type SupportedLocale,
} from "./language.ts";

const resources = {
  en: { translation: en },
  de: { translation: de },
  fr: { translation: fr },
  es: { translation: es },
  it: { translation: it },
  "pt-BR": { translation: ptBR },
  "zh-CN": { translation: zhCN },
  ja: { translation: ja },
  ko: { translation: ko },
  nl: { translation: nl },
  ru: { translation: ru },
  pl: { translation: pl },
  tr: { translation: tr },
  ca: { translation: ca },
};

export const initialLanguage = resolveInitialLanguage({
  saved: readStoredLanguage(),
  browserLanguages: getBrowserLanguages(),
  enabled: ENABLED_LOCALES,
});

void i18n.use(initReactI18next).init({
  resources,
  lng: initialLanguage,
  fallbackLng: "en",
  supportedLngs: [...SUPPORTED_LOCALES],
  interpolation: { escapeValue: false },
  returnEmptyString: false,
  initAsync: false,
  react: { useSuspense: false },
});

setDocumentLanguage(initialLanguage);
i18n.on("languageChanged", (language) => {
  setDocumentLanguage(language);
});

export function changeLanguage(language: SupportedLocale): Promise<unknown> {
  if (!ENABLED_LOCALES.includes(language)) return Promise.resolve(i18n.t);
  persistLanguage(language);
  return i18n.changeLanguage(language);
}

export default i18n;
