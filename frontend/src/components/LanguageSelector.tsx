import { Languages } from "lucide-react";
import { useTranslation } from "react-i18next";
import { changeLanguage, ENABLED_LOCALES, LOCALE_LABELS, type SupportedLocale } from "../i18n";

export default function LanguageSelector() {
  const { i18n, t } = useTranslation();
  const active = ENABLED_LOCALES.includes(i18n.language as SupportedLocale)
    ? (i18n.language as SupportedLocale)
    : "en";

  return (
    <label className="flex h-9 items-center gap-1 rounded-lg px-1.5 text-brand-gray">
      <Languages className="h-4 w-4" aria-hidden="true" />
      <span className="sr-only">{t("navigation.language")}</span>
      <select
        aria-label={t("navigation.language")}
        value={active}
        onChange={(event) => void changeLanguage(event.target.value as SupportedLocale)}
        className="max-w-28 cursor-pointer bg-transparent py-1 text-xs font-medium text-brand-dark-gray"
      >
        {ENABLED_LOCALES.map((locale) => (
          <option key={locale} value={locale}>{LOCALE_LABELS[locale]}</option>
        ))}
      </select>
    </label>
  );
}
