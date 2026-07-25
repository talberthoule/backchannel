import { useCallback, useEffect, useState } from "react";
import { useConfirm } from "./ConfirmProvider";
import * as api from "../services/api";
import type { CredentialInfo } from "../services/api";

// Self-hosted servers are configured per endpoint in EndpointsCard, not as a
// single workspace-wide key, so that provider is not listed here.
const COMPATIBLE = api.OPENAI_COMPATIBLE_PROVIDER;

const PROVIDER_LABELS: Record<string, string> = {
  google: "Google (Gemini)",
  openai: "OpenAI",
};

// Direct links to each provider's key-creation page so users never hunt
// through console menus.
const PROVIDER_KEY_PAGES: Record<string, string> = {
  google: "https://aistudio.google.com/apikey",
  openai: "https://platform.openai.com/api-keys",
};

interface ApiKeysCardProps {
  onChanged?: () => void;
}

export default function ApiKeysCard({ onChanged }: ApiKeysCardProps) {
  const { confirm, toast } = useConfirm();
  const [credentials, setCredentials] = useState<CredentialInfo[]>([]);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, { ok: boolean; message: string }>>({});

  const load = useCallback(async () => {
    try {
      const all = await api.listCredentials();
      setCredentials(all.filter((cred) => cred.provider !== COMPATIBLE));
    } catch (err) {
      console.error("Failed to load credentials", err);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const setResult = (provider: string, ok: boolean, message: string) =>
    setResults((prev) => ({ ...prev, [provider]: { ok, message } }));

  const handleSave = async (provider: string) => {
    const key = (inputs[provider] || "").trim();
    if (!key) return;
    setBusy(provider);
    try {
      const saved = await api.saveCredential(provider, key);
      setInputs((prev) => ({ ...prev, [provider]: "" }));
      setResult(provider, saved.connected, saved.message ?? "Saved");
      await load();
      onChanged?.();
    } catch (err) {
      setResult(provider, false, err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(null);
    }
  };

  const handleTest = async (provider: string) => {
    setBusy(provider);
    try {
      const res = await api.testCredential(provider);
      setResult(provider, res.ok, res.message);
      await load();
      onChanged?.();
    } catch (err) {
      setResult(provider, false, err instanceof Error ? err.message : "Test failed");
    } finally {
      setBusy(null);
    }
  };

  const handleRemove = async (provider: string) => {
    const ok = await confirm({
      title: "Remove API key",
      message: `Remove the stored ${provider} key? Live transcription and analysis that depend on it will stop working until you add a new key.`,
      confirmLabel: "Remove key",
      tone: "danger",
    });
    if (!ok) return;
    setBusy(provider);
    try {
      await api.deleteCredential(provider);
      setResult(provider, true, "Removed");
      toast(`${provider} key removed`);
      await load();
      onChanged?.();
    } catch (err) {
      setResult(provider, false, err instanceof Error ? err.message : "Remove failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="rounded-xl bg-surface p-5 shadow-sm">
      <h3 className="font-display text-base font-bold text-brand-dark-gray">Cloud Provider Keys</h3>
      <p className="mt-1 mb-4 font-body text-xs text-brand-gray leading-relaxed">
        Workspace keys are encrypted at rest and used by all agents. Environment variables remain a fallback.
        Self-hosted servers are configured below and usually need no key at all.
      </p>
      <div className="space-y-4">
        {credentials.map((cred) => {
          const isBusy = busy === cred.provider;
          const result = results[cred.provider];
          return (
            <div key={cred.provider} className={`transition-opacity ${isBusy ? "opacity-70" : ""}`}>
              <div className="flex items-center gap-2 mb-1">
                <label className="font-body text-xs font-medium text-brand-gray">
                  {PROVIDER_LABELS[cred.provider] || cred.provider}
                </label>
                {cred.configured || cred.env_fallback ? (
                  <>
                    <span className="inline-flex rounded-full bg-brand-teal px-2 py-0.5 text-[10px] font-medium text-white">
                      {cred.masked || "Key set"}
                    </span>
                    {cred.env_fallback && (
                      <span className="inline-flex rounded-full bg-brand-light-gray-1 px-2 py-0.5 text-[10px] font-medium text-brand-dark-gray">
                        Env var
                      </span>
                    )}
                    <span
                      className="inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium text-white"
                      style={{ backgroundColor: cred.connected ? "#72d54a" : "#ff9e16" }}
                      title={cred.connected ? "This key passed a connection test" : "Run Test to verify this key; unverified failing keys disable their provider's models"}
                    >
                      {cred.connected ? "Connected" : "Not verified"}
                    </span>
                  </>
                ) : (
                  <span className="inline-flex rounded-full bg-brand-light-gray-1 px-2 py-0.5 text-[10px] font-medium text-brand-dark-gray">
                    Not configured
                  </span>
                )}
                {PROVIDER_KEY_PAGES[cred.provider] && (
                  <a
                    href={PROVIDER_KEY_PAGES[cred.provider]}
                    target="_blank"
                    rel="noreferrer"
                    className="font-body text-[10px] font-medium text-brand-teal hover:underline"
                  >
                    Get a key
                  </a>
                )}
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="password"
                  placeholder={cred.configured ? "Replace key..." : "Paste API key..."}
                  value={inputs[cred.provider] || ""}
                  onChange={(e) => setInputs((prev) => ({ ...prev, [cred.provider]: e.target.value }))}
                  className="w-full max-w-md rounded border border-brand-light-gray-1 bg-surface px-3 py-1.5 font-mono text-sm text-brand-dark-gray focus:border-brand-teal"
                />
                <button
                  onClick={() => handleSave(cred.provider)}
                  disabled={isBusy || !(inputs[cred.provider] || "").trim()}
                  className="rounded bg-brand-teal px-3 py-1.5 font-body text-xs font-medium text-white transition-opacity disabled:opacity-40"
                >
                  Save
                </button>
                <button
                  onClick={() => handleTest(cred.provider)}
                  disabled={isBusy || (!cred.configured && !cred.env_fallback)}
                  className="rounded border border-brand-light-gray-1 px-3 py-1.5 font-body text-xs font-medium text-brand-dark-gray transition-opacity disabled:opacity-40"
                >
                  Test
                </button>
                {cred.configured && (
                  <button
                    onClick={() => handleRemove(cred.provider)}
                    disabled={isBusy}
                    className="rounded px-2 py-1.5 font-body text-xs text-brand-mid-gray hover:text-red-600 transition-colors disabled:opacity-40"
                  >
                    Remove
                  </button>
                )}
              </div>
              {result && (
                <p className={`mt-1 font-body text-xs ${result.ok ? "text-brand-teal" : "text-red-600"}`}>
                  {result.message}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
