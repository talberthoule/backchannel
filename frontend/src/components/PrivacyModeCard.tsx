import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { PrivacyConfig } from "../types";
import * as api from "../services/api";

interface PrivacyModeCardProps {
  config: PrivacyConfig | null;
  onChanged: (config: PrivacyConfig) => void;
}

export default function PrivacyModeCard({ config, onChanged }: PrivacyModeCardProps) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enabled = config?.local_only ?? false;

  const apply = async (localOnly: boolean) => {
    setSaving(true);
    try {
      onChanged(await api.updatePrivacyConfig(localOnly));
      setConfirming(false);
      setError(null);
    } catch (err) {
      console.error("Failed to update privacy mode", err);
      setError(err instanceof Error ? err.message : t("privacy.updateFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = () => {
    if (!config || saving) return;
    if (enabled) {
      void apply(false);
    } else {
      setConfirming((prev) => !prev);
    }
  };

  return (
    <div className={`rounded-xl bg-surface p-5 shadow-sm transition-opacity ${saving ? "opacity-70" : ""} ${enabled ? "ring-1 ring-brand-teal" : ""}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-display text-base font-bold text-brand-dark-gray">{t("privacy.title")}</h3>
            <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
              enabled
                ? "border-teal-600 bg-teal-700 text-white dark:border-teal-500 dark:bg-teal-900 dark:text-teal-100"
                : "border-slate-500 bg-slate-700 text-slate-50"
            }`}>
              {enabled ? t("privacy.localOnly") : t("privacy.cloudAllowed")}
            </span>
          </div>
          <p className="mt-1 font-body text-xs leading-relaxed text-brand-gray">
            {t("privacy.body")}
          </p>
        </div>
        <button
          onClick={handleToggle}
          disabled={!config || saving}
          className={`h-6 w-11 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed ${enabled ? "bg-brand-teal" : confirming ? "bg-amber-400" : "bg-brand-light-gray-1"}`}
          title={enabled ? t("privacy.turnOff") : t("privacy.turnOn")}
        >
          <span className={`block h-5 w-5 rounded-full bg-surface shadow transition-transform ${enabled ? "translate-x-5" : confirming ? "translate-x-2.5" : "translate-x-0.5"}`} />
        </button>
      </div>

      {enabled && config && (
        <p className="mt-3 rounded border border-brand-teal/30 bg-brand-teal/5 px-3 py-2 font-body text-xs text-brand-dark-gray">
          {t("privacy.active", { model: config.batch_model_id })}
        </p>
      )}

      {confirming && !enabled && config && (
        <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-900/50 dark:bg-amber-950/40">
          <p className="mb-3 font-body text-xs font-medium text-amber-900 dark:text-amber-200">
            {t("privacy.review")}
          </p>
          <ul className="mb-4 space-y-2">
            {config.impact.disabled.map((item) => (
              <li key={item.feature} className="flex gap-2">
                <span className="mt-0.5 shrink-0 text-red-500 dark:text-red-400" aria-hidden>✕</span>
                <div>
                  <p className="font-body text-xs font-semibold text-brand-dark-gray">{item.feature}</p>
                  <p className="font-body text-[11px] leading-relaxed text-brand-gray">{item.detail}</p>
                </div>
              </li>
            ))}
          </ul>
          <p className="mb-3 font-body text-xs font-medium text-amber-900 dark:text-amber-200">{t("privacy.keepWorking")}</p>
          <ul className="mb-4 space-y-2">
            {config.impact.available.map((item) => (
              <li key={item.feature} className="flex gap-2">
                <span className="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden>✓</span>
                <div>
                  <p className="font-body text-xs font-semibold text-brand-dark-gray">{item.feature}</p>
                  <p className="font-body text-[11px] leading-relaxed text-brand-gray">{item.detail}</p>
                </div>
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <button
              onClick={() => void apply(true)}
              disabled={saving}
              className="rounded bg-brand-teal px-4 py-1.5 font-body text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? t("privacy.enabling") : t("privacy.enable")}
            </button>
            <button
              onClick={() => setConfirming(false)}
              disabled={saving}
              className="rounded border border-brand-light-gray-1 px-4 py-1.5 font-body text-xs text-brand-dark-gray transition-colors hover:border-brand-teal hover:text-brand-teal disabled:cursor-not-allowed"
            >
              {t("common.cancel")}
            </button>
          </div>
        </div>
      )}

      {error && (
        <p className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 font-body text-xs text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-400">{error}</p>
      )}
    </div>
  );
}
