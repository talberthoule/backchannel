import { useEffect, useState } from "react";
import type { PiiCategory, PiiEgressEntry, PiiPreview, PiiShieldSettings, PiiShieldStatus } from "../types";
import * as api from "../services/api";
import { ModelDownloadRow } from "./ModelDownloads";

// The PII Shield settings card: the switch, what it covers (honestly), the
// categories it looks for, the user's own protected terms, the on-device
// model's state, and a scratch box to see what a sentence turns into.

const SAMPLE =
  "Hi, this is Sarah Connor from Cyberdyne. Email me at sarah.connor@cyberdyne.com or call 555-867-5309 about the Q3 renewal.";

const CATEGORY_HINTS: Partial<Record<PiiCategory, string>> = {
  PERSON: "Speaker names always; other names via the on-device model and introductions.",
  ORG: "Company names via the on-device model and your protected terms.",
  LOCATION: "Off by default: place names are usually analysis, not identity.",
};

const TERM_LABELS: Partial<Record<PiiCategory, string>> = { ORG: "org", PERSON: "person", LOCATION: "place" };

type Update = Partial<PiiShieldSettings>;

const checkboxClass = "h-4 w-4 rounded border-brand-light-gray-1 text-brand-teal";
const smallButtonClass =
  "rounded-md border border-brand-light-gray-1 px-2.5 py-1 font-body text-xs font-medium text-brand-dark-gray transition-colors hover:bg-brand-light-gray-2 disabled:opacity-60";

function CoverageRow({ label, covered, detail }: { label: string; covered: boolean; detail: string }) {
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
            {covered ? "protected" : "not covered"}
          </span>
        </p>
        <p className="font-body text-[11px] leading-relaxed text-brand-mid-gray">{detail}</p>
      </div>
    </li>
  );
}

function CoverageList({ status }: { status: PiiShieldStatus }) {
  const { coverage, settings } = status;
  const gateway = coverage.live_gateway;
  const refinement = coverage.refinement;
  const gatewayDetail = gateway.paused
    ? `${gateway.model_id} is configured but skipped while the shield is on: a cloud gateway would hear the names the shield withholds. Live captions stay off unless the Audio Bridge uses the on-device captioner.`
    : !gateway.covered
      ? `Live audio streams to ${gateway.model_id} for interim captions. Switch it to the on-device captioner or disable it in Agents.`
      : gateway.model_id
        ? `The gateway is on-device (${gateway.model_id}).`
        : "The audio gateway is off or has no model selected, so no live audio leaves this machine.";
  return (
    <ul className="mt-4 divide-y divide-brand-light-gray-2 rounded-lg border border-brand-light-gray-1 px-3">
      <CoverageRow
        label="Transcripts, insights, briefings, chat and documents"
        covered={coverage.text}
        detail={settings.enabled
          ? "Every line is tokenized as it is written, so each model prompt is built from clean text. Cloud text models receive tokens only."
          : "Turn the shield on to tokenize new text. Sessions recorded earlier keep what they hold until you protect them."}
      />
      <CoverageRow
        label="Transcription audio"
        covered={coverage.transcription.covered}
        detail={coverage.transcription.covered
          ? coverage.enforced
            ? `Audio cannot be tokenized, so while the shield is on transcription is held to a local model (${coverage.transcription.model_id}); cloud transcribers are locked in Transcription & Audio.`
            : `Transcription runs on this machine (${coverage.transcription.model_id}), so no audio leaves it.`
          : `Call audio goes to ${coverage.transcription.model_id} to be transcribed, and spoken names travel with it. Turn the shield on to hold transcription to a local model.`}
      />
      <CoverageRow label="Live captions (audio gateway)" covered={gateway.covered} detail={gatewayDetail} />
      {/* The badge answers a privacy question; whether the stage runs is a
          detail below it. Reading the agent's on/off switch as coverage put a
          red "not covered" on a state that leaks nothing (ALP-366). */}
      <CoverageRow
        label="Transcript refinement"
        covered={refinement.covered}
        detail={refinement.covered
          ? `The refiner only ever reads tokenized text, so it stays covered on any model, local or cloud, and a rewrite is kept only if it carries exactly the original tokens. ${refinement.enabled
              ? `Running now on ${refinement.model_id}, every ${refinement.interval_seconds}s and at call end.`
              : "Currently off; enable the Transcript Refiner in Agents to polish punctuation, casing and mishearings."}`
          : "Turn the shield on to tokenize new text; until then the refiner reads whatever the transcript holds."}
      />
    </ul>
  );
}

function CategoryPicker({ status, saving, onToggle }: { status: PiiShieldStatus; saving: boolean; onToggle: (id: PiiCategory) => void }) {
  return (
    <section>
      <h4 className="font-body text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">Looks for</h4>
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
              {CATEGORY_HINTS[category.id] && (
                <span className="block text-[11px] text-brand-mid-gray">{CATEGORY_HINTS[category.id]}</span>
              )}
            </span>
          </label>
        ))}
      </div>
    </section>
  );
}

function NerSection({ status, saving, onApply, onReload }: { status: PiiShieldStatus; saving: boolean; onApply: (u: Update) => void; onReload: () => Promise<void> }) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { ner, settings } = status;
  const label: Record<PiiShieldStatus["ner"]["state"], string> = {
    off: "Off",
    ready: "Ready",
    not_downloaded: settings.enabled ? "Not downloaded" : "Downloads when enabled",
    downloading: "Downloading",
    unavailable: "Unavailable",
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
      setError(err instanceof Error ? err.message : "The on-device model could not be installed.");
    } finally {
      setStarting(false);
    }
  };

  const running = ner.state === "downloading";

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-body text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">On-device name recognition</h4>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${badge}`}>{label[ner.state]}</span>
      </div>
      <p className="mt-1 font-body text-[11px] leading-relaxed text-brand-mid-gray">
        A small named-entity model ({ner.model}, about 110 MB) finds people, companies and places in free
        text. It downloads once and then runs offline on the CPU. Without it the shield still catches
        speaker names, protected terms, introductions, names it has seen before, and every structured identifier.
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
          Use the on-device model
        </label>
        {settings.ner && ner.state !== "ready" && !running && (
          <button type="button" onClick={() => void install()} disabled={starting} className={smallButtonClass}>
            {starting ? "Starting..." : ner.state === "unavailable" ? "Retry download" : "Download now"}
          </button>
        )}
      </div>
    </section>
  );
}

function TermsSection({ settings, saving, onApply }: { settings: PiiShieldSettings; saving: boolean; onApply: (u: Update) => void }) {
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
      <h4 className="font-body text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">Protected terms</h4>
      <p className="mt-1 font-body text-[11px] leading-relaxed text-brand-mid-gray">
        Names the model might miss and that must never leave this machine: client companies, project code
        names, a person who is never introduced. Matched as whole words in every session.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder="Acme Corporation"
          maxLength={200}
          className="min-w-[12rem] flex-1 rounded-md border border-brand-light-gray-1 bg-surface px-3 py-1.5 font-body text-xs text-brand-dark-gray placeholder:text-brand-mid-gray focus:border-brand-teal focus:ring-1 focus:ring-brand-teal-light"
        />
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as PiiCategory)}
          className="rounded-md border border-brand-light-gray-1 bg-surface px-2 py-1.5 font-body text-xs text-brand-dark-gray"
          aria-label="Term category"
        >
          <option value="ORG">Organization</option>
          <option value="PERSON">Person</option>
          <option value="LOCATION">Place</option>
        </select>
        <button
          type="button"
          onClick={add}
          disabled={saving || !value.trim()}
          className="rounded-md bg-brand-teal px-3 py-1.5 font-body text-xs font-semibold text-white transition-colors hover:bg-brand-teal-dark disabled:opacity-50"
        >
          Add
        </button>
      </div>
      {settings.protected_terms.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {settings.protected_terms.map((term) => (
            <li key={term.value} className="inline-flex items-center gap-1 rounded-full border border-brand-light-gray-1 bg-brand-light-gray-2 py-0.5 pl-2.5 pr-1 font-body text-xs text-brand-dark-gray">
              {term.value}
              <span className="text-[10px] uppercase text-brand-mid-gray">{TERM_LABELS[term.category] ?? term.category.toLowerCase()}</span>
              <button
                type="button"
                onClick={() => remove(term.value)}
                aria-label={`Remove ${term.value}`}
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
      setError(err instanceof Error ? err.message : "Preview failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h4 className="font-body text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">Try a sentence</h4>
      <textarea
        value={sample}
        onChange={(e) => setSample(e.target.value)}
        rows={3}
        className="mt-2 w-full resize-none rounded-md border border-brand-light-gray-1 bg-surface px-3 py-2 font-body text-xs text-brand-dark-gray focus:border-brand-teal focus:ring-1 focus:ring-brand-teal-light"
      />
      <div className="mt-2 flex items-center gap-3">
        <button type="button" onClick={() => void run()} disabled={busy || !sample.trim()} className={`px-3 py-1.5 ${smallButtonClass}`}>
          {busy ? "Scanning..." : "Show what a model would see"}
        </button>
        <span className="font-body text-[11px] text-brand-mid-gray">Nothing is stored; the preview numbers tokens from 1.</span>
      </div>
      {error && <p className="mt-2 font-body text-xs text-red-700">{error}</p>}
      {preview && (
        <div className="mt-3 rounded-md border border-brand-light-gray-1 bg-brand-light-gray-2/60 p-3">
          <p className="font-mono text-xs leading-relaxed text-brand-dark-gray">{preview.protected}</p>
          {preview.findings.length === 0 ? (
            <p className="mt-2 font-body text-[11px] text-brand-mid-gray">Nothing in that text matched the enabled categories.</p>
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
        <h4 className="font-body text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">Outbound prompts</h4>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => void load()} disabled={busy} className={smallButtonClass}>{busy ? "Loading..." : "Refresh"}</button>
          <button type="button" onClick={() => void clear()} disabled={busy || entries.length === 0} className={smallButtonClass}>Clear log</button>
        </div>
      </div>
      <p className="mt-1 font-body text-[11px] leading-relaxed text-brand-mid-gray">
        With the log on, every prompt is written to the data directory exactly as it leaves for a model,
        so you can confirm the models only ever see tokens. While the shield is on, a prompt that still
        carries a vault value is refused before it is sent and appears here marked blocked.
      </p>
      <label className="mt-2 flex items-center gap-2 font-body text-xs text-brand-dark-gray">
        <input
          type="checkbox"
          checked={settings.prompt_log}
          onChange={(e) => onApply({ prompt_log: e.target.checked })}
          disabled={saving}
          className={checkboxClass}
        />
        Record outbound prompts
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
                  <span className="font-body text-[11px] text-brand-mid-gray">{entry.chars.toLocaleString()} chars</span>
                  {entry.blocked ? (
                    <span className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-semibold text-red-700">blocked: {entry.leaks.map((l) => l.category).join(", ")}</span>
                  ) : entry.tokens_present ? (
                    <span className="rounded-full bg-brand-teal/10 px-2 py-0.5 text-[10px] font-semibold text-brand-teal">tokens only</span>
                  ) : (
                    <span className="rounded-full bg-brand-light-gray-2 px-2 py-0.5 text-[10px] font-semibold text-brand-mid-gray">no tokens</span>
                  )}
                </button>
                {expanded && (
                  <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded bg-brand-light-gray-2/60 p-2 font-mono text-[11px] leading-relaxed text-brand-dark-gray">{entry.prompt}{entry.truncated ? "\n[truncated]" : ""}</pre>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

export default function PiiShieldCard({ onChanged }: { onChanged?: (status: PiiShieldStatus) => void }) {
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
      setError(err instanceof Error ? err.message : "Unable to load the PII Shield.");
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
      setError(err instanceof Error ? err.message : "Unable to update the PII Shield.");
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
            <h3 className="font-display text-base font-bold text-brand-dark-gray">PII Shield</h3>
            <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
              enabled
                ? "border-teal-600 bg-teal-700 text-white dark:border-teal-500 dark:bg-teal-900 dark:text-teal-100"
                : "border-slate-500 bg-slate-700 text-slate-50"
            }`}>
              {enabled ? "Personal data tokenized" : "Personal data stored as spoken"}
            </span>
          </div>
          <p className="mt-1 font-body text-xs leading-relaxed text-brand-gray">
            Replaces names, contact details and identifiers with tokens such as
            <span className="font-mono"> [PERSON_1]</span> before anything is stored or shown to a
            model, local or cloud. The real values sit in an encrypted vault on this machine and
            are put back only on the screen in front of you and in exports you ask for.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void apply({ enabled: !enabled })}
          disabled={!status || saving}
          role="switch"
          aria-checked={enabled}
          aria-label={enabled ? "Turn off the PII Shield" : "Turn on the PII Shield"}
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
          Vault: {plural(status.vault.entries, "protected value")} across all sessions.
          Revealed to this screen in the last 24 hours: {plural(status.reveals_24h.tokens, "token")} over {plural(status.reveals_24h.requests, "request")}.
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
        {showDetails ? "Hide" : "Show"} what it looks for and try a sentence
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
