export const LANGUAGE_STORAGE_KEY = "bc-language";

export const SUPPORTED_LOCALES = [
  "en",
  "de",
  "fr",
  "es",
  "it",
  "pt-BR",
  "zh-CN",
  "ja",
  "ko",
  "nl",
  "ru",
  "pl",
  "tr",
  "ca",
] as const;

export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export const LOCALE_LABELS: Record<SupportedLocale, string> = {
  en: "English",
  de: "Deutsch",
  fr: "Français",
  es: "Español",
  it: "Italiano",
  "pt-BR": "Português (Brasil)",
  "zh-CN": "简体中文",
  ja: "日本語",
  ko: "한국어",
  nl: "Nederlands",
  ru: "Русский",
  pl: "Polski",
  tr: "Türkçe",
  ca: "Català",
};

// Every catalog is enabled only after external translation and strict validation.
export const ENABLED_LOCALES: readonly SupportedLocale[] = SUPPORTED_LOCALES;

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function normalizedLanguageTag(value: string): string {
  return value.trim().replace(/_/g, "-").toLowerCase();
}

export function mapBrowserLanguage(value: string | null | undefined): SupportedLocale | null {
  if (!value) return null;
  const tag = normalizedLanguageTag(value);
  if (!tag) return null;

  if (tag === "pt" || tag === "pt-br") return "pt-BR";
  if (tag === "pt-pt") return null;
  if (tag === "zh" || tag === "zh-cn" || tag === "zh-hans" || tag.startsWith("zh-hans-")) {
    return "zh-CN";
  }

  const base = tag.split("-")[0];
  if (base === "en") return "en";
  if (base === "de") return "de";
  if (base === "fr") return "fr";
  if (base === "es") return "es";
  if (base === "it") return "it";
  if (base === "ja") return "ja";
  if (base === "ko") return "ko";
  if (base === "nl") return "nl";
  if (base === "ru") return "ru";
  if (base === "pl") return "pl";
  if (base === "tr") return "tr";
  if (base === "ca") return "ca";
  return null;
}

function browserStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function readStoredLanguage(storage: StorageLike | null = browserStorage()): SupportedLocale | null {
  if (!storage) return null;
  try {
    const saved = storage.getItem(LANGUAGE_STORAGE_KEY);
    return SUPPORTED_LOCALES.includes(saved as SupportedLocale) ? (saved as SupportedLocale) : null;
  } catch {
    return null;
  }
}

export function persistLanguage(
  language: SupportedLocale,
  storage: StorageLike | null = browserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // A blocked or full storage area must not interrupt the live language switch.
  }
}

export function resolveInitialLanguage({
  saved,
  browserLanguages,
  enabled,
}: {
  saved: string | null | undefined;
  browserLanguages: readonly string[];
  enabled: readonly SupportedLocale[];
}): SupportedLocale {
  const savedLocale = SUPPORTED_LOCALES.includes(saved as SupportedLocale)
    ? (saved as SupportedLocale)
    : null;
  if (savedLocale && enabled.includes(savedLocale)) return savedLocale;

  for (const browserLanguage of browserLanguages) {
    const locale = mapBrowserLanguage(browserLanguage);
    if (locale && enabled.includes(locale)) return locale;
  }
  return "en";
}

export function getBrowserLanguages(): string[] {
  if (typeof navigator === "undefined") return [];
  if (Array.isArray(navigator.languages) && navigator.languages.length > 0) {
    return [...navigator.languages];
  }
  return navigator.language ? [navigator.language] : [];
}

export function setDocumentLanguage(language: string): void {
  if (typeof document !== "undefined") {
    document.documentElement.lang = language;
  }
}
