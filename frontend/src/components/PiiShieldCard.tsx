import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { PiiCategory, PiiEgressEntry, PiiPreview, PiiShieldSettings, PiiShieldStatus } from "../types";
import * as api from "../services/api";
import { ModelDownloadRow } from "./ModelDownloads";

// The PII Shield settings card: the switch, what it covers (honestly), the
// categories it looks for, the user's own protected terms, the on-device
// model's state, and a scratch box to see what a sentence turns into.

const SAMPLE =
  "Hi, this is Sarah Connor from Cyberdyne. Email me at sarah.connor@cyberdyne.com or call 555-867-5309 about the Q3 renewal.";

const CATEGORY_HINT_KEYS: Partial<Record<PiiCategory, string>> = {
  PERSON: "pii.categoryHints.person",
  ORG: "pii.categoryHints.org",
  LOCATION: "pii.categoryHints.location",
};

const TERM_LABEL_KEYS: Partial<Record<PiiCategory, string>> = {
  ORG: "pii.termLabels.org",
  PERSON: "pii.termLabels.person",
  LOCATION: "pii.termLabels.place",
};

type Update = Partial<PiiShieldSettings>;

const checkboxClass = "h-4 w-4 rounded border-brand-light-gray-1 text-brand-teal";
const smallButtonClass =
  "rounded-md border border-brand-light-gray-1 px-2.5 py-1 font-body text-xs font-medium text-brand-dark-gray transition-colors hover:bg-brand-light-gray-2 disabled:opacity-60";

function CoverageRow({ label, covered, detail }: { label: string; covered: boolean; detail: string }) {
  const { t } = useTranslation();
  return (
    <li className="flex items-start gap-2.5 py-1.5">
      <span
        aria-hidden="true"
        className={`mt-1 inline-block h-2 w-2 shrink-0 rounded-full ${covered ? "bg-brand-teal" : "bg-amber-500"}`}
      />
      <div className="min-w-0">
        <p className="font-body text-xs font-semibold text-brand-dark-gray">
          {label}
          <span className={`ml-2 font-normal ${covered ? "text-brand-teal" : "text-amber-700 dark:text-amber-300"}`}>
            {covered ? t("pii.protected") : t("pii.notCovered")}
          </span>
        </p>
        <p className="font-body text-[11px] leading-relaxed text-brand-mid-gray">{detail}</p>
      </div>
    </li>
  );
}

function CoverageList({ status }: { status: PiiShieldStatus }) {
  const { t } = useTranslation();
  const { coverage, settings } = status;
  const gateway = coverage.live_gateway;
  const refinement = coverage.refinement;
  const gatewayDetail = gateway.paused
    ? t("pii.coverage.gatewayPaused", { model: gateway.model_id })
    : !gateway.covered
      ? t("pii.coverage.gatewayCloud", { model: gateway.model_id })
      : gateway.model_id
        ? t("pii.coverage.gatewayLocal", { model: gateway.model_id })
        : t("pii.coverage.gatewayOff");
  return (
    <ul className="mt-4 divide-y divide-brand-light-gray-2 rounded-lg border border-brand-light-gray-1 px-3">
      <CoverageRow
        label={t("pii.coverage.text")}
        covered={coverage.text}
        detail={settings.enabled
          ? t("pii.coverage.textOn")
          : t("pii.coverage.textOff")}
      />
      <CoverageRow
        label={t("pii.coverage.audio")}
        covered={coverage.transcription.covered}
        detail={coverage.transcription.covered
          ? coverage.enforced
            ? t("pii.coverage.audioEnforced", { model: coverage.transcription.model_id })
            : t("pii.coverage.audioLocal", { model: coverage.transcription.model_id })
          : t("pii.coverage.audioCloud", { model: coverage.transcription.model_id })}
      />
      <CoverageRow label={t("pii.coverage.captions")} covered={gateway.covered} detail={gatewayDetail} />
      {/* The badge answers a privacy question; whether the stage runs is a
          detail below it. Reading the agent's on/off switch as coverage put a
          red "not covered" on a state that leaks nothing (ALP-366). */}
      <CoverageRow
        label={t("pii.coverage.refinement")}
        covered={refinement.covered}
        detail={refinement.covered
          ? t("pii.coverage.refinementOn", {
              status: refinement.enabled
                ? t("pii.coverage.refinementRunning", {
                    model: refinement.model_id,
                    seconds: refinement.interval_seconds,
                  })
                : t("pii.coverage.refinementOff"),
            })
          : t("pii.coverage.refinementDisabled")}
      />
    </ul>
  );
}

function CategoryPicker({ status, saving, onToggle }: { status: PiiShieldStatus; saving: boolean; onToggle: (id: PiiCategory) => void }) {
  const { t } = useTranslation();
  return (
    <section>
      <h4 className="font-body text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">{t("pii.looksFor")}</h4>
      <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
        {status.categories.map((category) => (
          <label key={category.id} className="flex cursor-pointer items-start gap-2 rounded-md px-1.5 py-1 hover:bg-brand-light-gray-2">
            <input
              type="checkbox"
              checked={status.settings.categories.includes(category.id)}
              onChange={() => onToggle(category.id)}
              disabled={saving}
              className={`mt-0.5 ${checkboxClass}`}
            />
            <span className="font-body text-xs text-brand-dark-gray">
              {category.label}
              {CATEGORY_HINT_KEYS[category.id] && (
                <span className="block text-[11px] text-brand-mid-gray">{t(CATEGORY_HINT_KEYS[category.id]!)}</span>
              )}
            </span>
          </label>
        ))}
      </div>
    </section>
  );
}

function NerSection({ status, saving, onApply, onReload }: { status: PiiShieldStatus; saving: boolean; onApply: (u: Update) => void; onReload: () => Promise<void> }) {
  const { t } = useTranslation();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { ner, settings } = status;
  const label: Record<PiiShieldStatus["ner"]["state"], string> = {
    off: t("pii.nerState.off"),
    ready: t("pii.nerState.ready"),
    not_downloaded: settings.enabled ? t("pii.nerState.notDownloaded") : t("pii.nerState.downloadsWhenEnabled"),
    downloading: t("pii.nerState.downloading"),
    unavailable: t("pii.nerState.unavailable"),
  };
  const badge = ner.state === "ready"
    ? "bg-brand-teal/10 text-brand-teal"
    : ner.state === "unavailable" ? "bg-red-50 text-red-700"
      : ner.state === "downloading" ? "bg-amber-50 text-amber-700"
        : "bg-brand-light-gray-2 text-brand-mid-gray";

  // Kicks the download off and returns; the progress row below reports it.
  // Waiting on the transfer here is what made the button look like a hang.
  const install = async () => {
    setStarting(true);
    setError(null);
    try {
      await api.installPiiNer();
      await onReload();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("pii.nerInstallFailed"));
    } finally {
      setStarting(false);
    }
  };

  const running = ner.state === "downloading";

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-body text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">{t("pii.nerTitle")}</h4>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${badge}`}>{label[ner.state]}</span>
      </div>
      <p className="mt-1 font-body text-[11px] leading-relaxed text-brand-mid-gray">
        {t("pii.nerBody", { model: ner.model })}
      </p>
      {(error || (ner.state === "unavailable" && ner.error && !ner.download)) && (
        <p className="mt-1 font-mono text-[11px] text-red-700">{error || ner.error}</p>
      )}
      {ner.download && (
        <ModelDownloadRow download={ner.download} onRetry={() => void install()} />
      )}
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 font-body text-xs text-brand-dark-gray">
          <input
            type="checkbox"
            checked={settings.ner}
            onChange={(e) => onApply({ ner: e.target.checked })}
            disabled={saving}
            className={checkboxClass}
          />
          {t("pii.useNer")}
        </label>
        {settings.ner && ner.state !== "ready" && !running && (
          <button type="button" onClick={() => void install()} disabled={starting} className={smallButtonClass}>
            {starting ? t("pii.starting") : ner.state === "unavailable" ? t("pii.retryDownload") : t("pii.downloadNow")}
          </button>
        )}
      </div>
    </section>
  );
}

function TermsSection({ settings, saving, onApply }: { settings: PiiShieldSettings; saving: boolean; onApply: (u: Update) => void }) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const [category, setCategory] = useState<PiiCategory>("ORG");

  const add = () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    setValue("");
    if (settings.protected_terms.some((t) => t.value.toLowerCase() === trimmed.toLowerCase())) return;
    onApply({ protected_terms: [...settings.protected_terms, { value: trimmed, category }] });
  };
  const remove = (term: string) =>
    onApply({ protected_terms: settings.protected_terms.filter((t) => t.value !== term) });

  return (
    <section>
      <h4 className="font-body text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">{t("pii.termsTitle")}</h4>
      <p className="mt-1 font-body text-[11px] leading-relaxed text-brand-mid-gray">
        {t("pii.termsBody")}
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder={t("pii.termPlaceholder")}
          maxLength={200}
          className="min-w-[12rem] flex-1 rounded-md border border-brand-light-gray-1 bg-surface px-3 py-1.5 font-body text-xs text-brand-dark-gray placeholder:text-brand-mid-gray focus:border-brand-teal focus:ring-1 focus:ring-brand-teal-light"
        />
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as PiiCategory)}
          className="rounded-md border border-brand-light-gray-1 bg-surface px-2 py-1.5 font-body text-xs text-brand-dark-gray"
          aria-label={t("pii.termCategory")}
        >
          <option value="ORG">{t("pii.organization")}</option>
          <option value="PERSON">{t("pii.person")}</option>
          <option value="LOCATION">{t("pii.place")}</option>
        </select>
        <button
          type="button"
          onClick={add}
          disabled={saving || !value.trim()}
          className="rounded-md bg-brand-teal px-3 py-1.5 font-body text-xs font-semibold text-white transition-colors hover:bg-brand-teal-dark disabled:opacity-50"
        >
          {t("common.add")}
        </button>
      </div>
      {settings.protected_terms.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {settings.protected_terms.map((term) => (
            <li key={term.value} className="inline-flex items-center gap-1 rounded-full border border-brand-light-gray-1 bg-brand-light-gray-2 py-0.5 pl-2.5 pr-1 font-body text-xs text-brand-dark-gray">
              {term.value}
              <span className="text-[10px] uppercase text-brand-mid-gray">
                {TERM_LABEL_KEYS[term.category] ? t(TERM_LABEL_KEYS[term.category]!) : term.category.toLowerCase()}
              </span>
              <button
                type="button"
                onClick={() => remove(term.value)}
                aria-label={t("pii.removeTerm", { term: term.value })}
                className="rounded-full p-0.5 text-brand-mid-gray hover:bg-brand-light-gray-1 hover:text-brand-dark-gray"
              >
                <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                </svg>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function PreviewSection() {
  const { t } = useTranslation();
  const [sample, setSample] = useState(SAMPLE);
  const [preview, setPreview] = useState<PiiPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (!sample.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setPreview(await api.previewPiiShield(sample));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("pii.previewFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h4 className="font-body text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">{t("pii.trySentence")}</h4>
      <textarea
        value={sample}
        onChange={(e) => setSample(e.target.value)}
        rows={3}
        className="mt-2 w-full resize-none rounded-md border border-brand-light-gray-1 bg-surface px-3 py-2 font-body text-xs text-brand-dark-gray focus:border-brand-teal focus:ring-1 focus:ring-brand-teal-light"
      />
      <div className="mt-2 flex items-center gap-3">
        <button type="button" onClick={() => void run()} disabled={busy || !sample.trim()} className={`px-3 py-1.5 ${smallButtonClass}`}>
          {busy ? t("pii.scanning") : t("pii.showPreview")}
        </button>
        <span className="font-body text-[11px] text-brand-mid-gray">{t("pii.previewHint")}</span>
      </div>
      {error && <p className="mt-2 font-body text-xs text-red-700">{error}</p>}
      {preview && (
        <div className="mt-3 rounded-md border border-brand-light-gray-1 bg-brand-light-gray-2/60 p-3">
          <p className="font-mono text-xs leading-relaxed text-brand-dark-gray">{preview.protected}</p>
          {preview.findings.length === 0 ? (
            <p className="mt-2 font-body text-[11px] text-brand-mid-gray">{t("pii.noMatches")}</p>
          ) : (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {preview.findings.map((f, i) => (
                <li key={i} className="rounded-full border border-brand-light-gray-1 bg-surface px-2 py-0.5 font-body text-[11px] text-brand-dark-gray">
                  <span className="font-mono">{f.token}</span> = {f.text}
                  <span className="ml-1 text-brand-mid-gray">({f.source})</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

// What actually left for the models: the prompt log, newest first. Tokens
// show as tokens here (the route is not session-scoped), which is the point.
function EgressSection({ settings, saving, onApply }: { settings: PiiShieldSettings; saving: boolean; onApply: (u: Update) => void }) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<PiiEgressEntry[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      setEntries((await api.getPiiEgress(50)).entries);
    } catch (err) {
      console.error("Failed to load the prompt log", err);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const clear = async () => {
    await api.clearPiiEgress().catch(() => {});
    setEntries([]);
  };

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-body text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">{t("pii.outbound")}</h4>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => void load()} disabled={busy} className={smallButtonClass}>{busy ? t("pii.loading") : t("pii.refresh")}</button>
          <button type="button" onClick={() => void clear()} disabled={busy || entries.length === 0} className={smallButtonClass}>{t("pii.clearLog")}</button>
        </div>
      </div>
      <p className="mt-1 font-body text-[11px] leading-relaxed text-brand-mid-gray">
        {t("pii.outboundBody")}
      </p>
      <label className="mt-2 flex items-center gap-2 font-body text-xs text-brand-dark-gray">
        <input
          type="checkbox"
          checked={settings.prompt_log}
          onChange={(e) => onApply({ prompt_log: e.target.checked })}
          disabled={saving}
          className={checkboxClass}
        />
        {t("pii.recordPrompts")}
      </label>
      {entries.length > 0 && (
        <ul className="mt-3 divide-y divide-brand-light-gray-2 rounded-md border border-brand-light-gray-1">
          {entries.map((entry, i) => {
            const key = `${entry.at}-${i}`;
            const expanded = open === key;
            return (
              <li key={key} className="px-3 py-2">
                <button type="button" onClick={() => setOpen(expanded ? null : key)} aria-expanded={expanded} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-left">
                  <span className="font-mono text-[11px] text-brand-mid-gray">{new Date(entry.at).toLocaleTimeString()}</span>
                  <span className="font-body text-xs font-semibold text-brand-dark-gray">{entry.source || "text"}</span>
                  <span className="font-mono text-[11px] text-brand-mid-gray">{entry.model_id}</span>
                  <span className="font-body text-[11px] text-brand-mid-gray">{t("pii.chars", { value: entry.chars.toLocaleString() })}</span>
                  {entry.blocked ? (
                    <span className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-semibold text-red-700">{t("pii.blocked", { categories: entry.leaks.map((l) => l.category).join(", ") })}</span>
                  ) : entry.tokens_present ? (
                    <span className="rounded-full bg-brand-teal/10 px-2 py-0.5 text-[10px] font-semibold text-brand-teal">{t("pii.tokensOnly")}</span>
                  ) : (
                    <span className="rounded-full bg-brand-light-gray-2 px-2 py-0.5 text-[10px] font-semibold text-brand-mid-gray">{t("pii.noTokens")}</span>
                  )}
                </button>
                {expanded && (
                  <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded bg-brand-light-gray-2/60 p-2 font-mono text-[11px] leading-relaxed text-brand-dark-gray">{entry.prompt}{entry.truncated ? `\n${t("pii.truncated")}` : ""}</pre>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export default function PiiShieldCard({ onChanged }: { onChanged?: (status: PiiShieldStatus) => void }) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<PiiShieldStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showDetails, setShowDetails] = useState(false);

  const load = async () => {
    try {
      const next = await api.getPiiShield();
      setStatus(next);
      onChanged?.(next);
    } catch (err) {
      console.error("Failed to load PII Shield status", err);
      setError(err instanceof Error ? err.message : t("pii.loadFailed"));
    }
  };

  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // While the model downloads, poll until it is ready or fails.
  const downloading = Boolean(status?.settings.enabled && status.settings.ner && status.ner.state === "downloading");
  useEffect(() => {
    if (!downloading) return;
    const id = window.setInterval(() => { void load(); }, 2000);
    return () => window.clearInterval(id);
  }, [downloading]); // eslint-disable-line react-hooks/exhaustive-deps

  const apply = async (update: Update) => {
    setSaving(true);
    setError(null);
    try {
      const next = await api.updatePiiShield(update);
      setStatus(next);
      onChanged?.(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("pii.updateFailed"));
    } finally {
      setSaving(false);
    }
  };

  const enabled = status?.settings.enabled ?? false;
  const toggleCategory = (id: PiiCategory) => {
    if (!status) return;
    const current = status.settings.categories;
    void apply({ categories: current.includes(id) ? current.filter((c) => c !== id) : [...current, id] });
  };

  return (
    <div className={`rounded-xl bg-surface p-5 shadow-sm transition-opacity ${saving ? "opacity-70" : ""} ${enabled ? "ring-1 ring-brand-teal" : ""}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-display text-base font-bold text-brand-dark-gray">{t("pii.title")}</h3>
            <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
              enabled
                ? "border-teal-600 bg-teal-700 text-white dark:border-teal-500 dark:bg-teal-900 dark:text-teal-100"
                : "border-slate-500 bg-slate-700 text-slate-50"
            }`}>
              {enabled ? t("pii.onBadge") : t("pii.offBadge")}
            </span>
          </div>
          <p className="mt-1 font-body text-xs leading-relaxed text-brand-gray">
            {t("pii.body")}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void apply({ enabled: !enabled })}
          disabled={!status || saving}
          role="switch"
          aria-checked={enabled}
          aria-label={enabled ? t("pii.turnOff") : t("pii.turnOn")}
          className={`h-6 w-11 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed ${enabled ? "bg-brand-teal" : "bg-brand-light-gray-1"}`}
        >
          <span className={`block h-5 w-5 rounded-full bg-surface shadow transition-transform ${enabled ? "translate-x-5" : "translate-x-0.5"}`} />
        </button>
      </div>

      {error && (
        <p className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 font-body text-xs text-red-700">{error}</p>
      )}

      {status && <CoverageList status={status} />}

      {status && enabled && (
        <p className="mt-3 font-body text-[11px] text-brand-mid-gray">
          {t("pii.vault", {
            values: t("pii.protectedValue", { count: status.vault.entries }),
            tokens: t("pii.token", { count: status.reveals_24h.tokens }),
            requests: t("pii.request", { count: status.reveals_24h.requests }),
          })}
        </p>
      )}

      <button
        type="button"
        onClick={() => setShowDetails((v) => !v)}
        aria-expanded={showDetails}
        className="mt-3 inline-flex items-center gap-1.5 font-body text-xs font-semibold text-brand-teal hover:underline"
      >
        <svg className={`h-3 w-3 transition-transform ${showDetails ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        {showDetails ? t("pii.hide") : t("pii.show")} {t("pii.detailsToggle")}
      </button>

      {showDetails && status && (
        <div className="mt-4 space-y-5">
          <CategoryPicker status={status} saving={saving} onToggle={toggleCategory} />
          <NerSection status={status} saving={saving} onApply={(u) => void apply(u)} onReload={load} />
          <TermsSection settings={status.settings} saving={saving} onApply={(u) => void apply(u)} />
          <PreviewSection />
          <EgressSection settings={status.settings} saving={saving} onApply={(u) => void apply(u)} />
        </div>
      )}
    </div>
  );
}
