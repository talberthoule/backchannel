import { useCallback, useEffect, useState } from "react";
import { useConfirm } from "./ConfirmProvider";
import * as api from "../services/api";
import type { CredentialInfo, TextEndpointConfig } from "../services/api";

const COMPATIBLE = api.OPENAI_COMPATIBLE_PROVIDER;

const PROVIDER_LABELS: Record<string, string> = {
  google: "Google (Gemini)",
  openai: "OpenAI",
  [COMPATIBLE]: "OpenAI-Compatible Endpoint",
};

// Direct links to each provider's key-creation page so users never hunt
// through console menus. The self-hosted endpoint has no such page.
const PROVIDER_KEY_PAGES: Record<string, string> = {
  google: "https://aistudio.google.com/apikey",
  openai: "https://platform.openai.com/api-keys",
};

// Base URL and model id for a self-hosted OpenAI-compatible chat server.
// Both are optional: unset leaves the backend on its built-in defaults, so an
// untouched workspace behaves exactly as it did before this section existed.
function TextEndpointFields({ onSaved }: { onSaved?: () => void }) {
  const [config, setConfig] = useState<TextEndpointConfig | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [modelId, setModelId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const apply = (next: TextEndpointConfig) => {
    setConfig(next);
    setBaseUrl(next.base_url);
    setModelId(next.model_id);
  };

  useEffect(() => {
    api.getTextEndpoint().then(apply).catch((err) => console.error("Failed to load text endpoint", err));
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      apply(await api.saveTextEndpoint({ base_url: baseUrl, model_id: modelId }));
      setMessage({ ok: true, text: "Saved" });
      onSaved?.();
    } catch (err) {
      setMessage({ ok: false, text: err instanceof Error ? err.message : "Save failed" });
    } finally {
      setBusy(false);
    }
  };

  const dirty = !!config && (baseUrl !== config.base_url || modelId !== config.model_id);

  return (
    <div className={`mt-2 rounded border border-brand-light-gray-1 bg-brand-light-gray-2/30 p-3 transition-opacity ${busy ? "opacity-70" : ""}`}>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <label className="mb-1 block font-body text-[10px] font-medium text-brand-gray">Base URL</label>
          <input
            type="text"
            value={baseUrl}
            placeholder={config?.fallback_base_url || "http://localhost:11434/v1"}
            onChange={(e) => setBaseUrl(e.target.value)}
            className="w-full rounded border border-brand-light-gray-1 bg-surface px-2.5 py-1.5 font-mono text-xs text-brand-dark-gray focus:border-brand-teal"
          />
        </div>
        <div>
          <label className="mb-1 block font-body text-[10px] font-medium text-brand-gray">Model id</label>
          <input
            type="text"
            value={modelId}
            placeholder="llama3.1:8b"
            onChange={(e) => setModelId(e.target.value)}
            className="w-full rounded border border-brand-light-gray-1 bg-surface px-2.5 py-1.5 font-mono text-xs text-brand-dark-gray focus:border-brand-teal"
          />
        </div>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <button
          onClick={save}
          disabled={busy || !dirty}
          className="rounded bg-brand-teal px-3 py-1.5 font-body text-xs font-medium text-white transition-opacity disabled:opacity-40"
        >
          Save endpoint
        </button>
        <p className="font-body text-[10px] text-brand-mid-gray">
          Ollama uses http://localhost:11434/v1, LM Studio http://localhost:1234/v1. Leave both blank to
          keep the built-in defaults. Pick &quot;OpenAI-Compatible Endpoint&quot; as an agent&apos;s model to use it.
        </p>
      </div>
      {message && (
        <p className={`mt-1 font-body text-xs ${message.ok ? "text-brand-teal" : "text-red-600"}`}>{message.text}</p>
      )}
    </div>
  );
}

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
      setCredentials(await api.listCredentials());
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
      <h3 className="font-display text-base font-bold text-brand-dark-gray">API Keys</h3>
      <p className="mt-1 mb-4 font-body text-xs text-brand-gray leading-relaxed">
        Workspace keys are encrypted at rest and used by all agents. Environment variables remain a fallback.
      </p>
      <div className="space-y-4">
        {credentials.map((cred) => {
          const isBusy = busy === cred.provider;
          const result = results[cred.provider];
          // A self-hosted server usually needs no key, so its row must not
          // read as broken when none is stored and Test must stay usable.
          const keyOptional = cred.provider === COMPATIBLE;
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
                    {keyOptional ? "No key needed" : "Not configured"}
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
                  placeholder={cred.configured ? "Replace key..." : keyOptional ? "Optional API key..." : "Paste API key..."}
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
                  disabled={isBusy || (!keyOptional && !cred.configured && !cred.env_fallback)}
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
              {keyOptional && <TextEndpointFields onSaved={onChanged} />}
            </div>
          );
        })}
      </div>
    </div>
  );
}
