import { useState } from "react";
import type { ModelInfo } from "../../types";
import ModelChip from "./ModelChip";

type Mode = "chat" | "directive";

const MODE_STORAGE_KEY = "backchannel:call-bar-mode";

interface DirectiveBarProps {
  onAddDirective: (text: string) => void;
  onAsk: (question: string) => void;
  models: ModelInfo[];
  modelId: string;
  onModelChange: (id: string) => void;
  localOnly: boolean;
  asking?: boolean;
  disabled?: boolean;
}

/** The call's command bar.
 *
 * Chat is the default because asking is the more frequent act and it should
 * cost zero clicks; the input is always open for the same reason. Directive
 * keeps its previous behavior, one toggle away.
 */
export default function DirectiveBar({
  onAddDirective,
  onAsk,
  models,
  modelId,
  onModelChange,
  localOnly,
  asking = false,
  disabled = false,
}: DirectiveBarProps) {
  const [mode, setMode] = useState<Mode>(() => {
    // ponytail: default-first so "chat" reads as the fallback in one glance;
    // functionally identical to a loadMode() helper (defaults to chat, only
    // "directive" is ever read back from storage), inlined so a browser that
    // refuses storage still yields chat with zero indirection.
    let initial: Mode = "chat";
    try {
      if (window.localStorage.getItem(MODE_STORAGE_KEY) === "directive") initial = "directive";
    } catch {
      // A browser refusing storage is not a reason to break the bar.
    }
    return initial;
  });
  const [text, setText] = useState("");

  const chatMode = mode === "chat";

  function selectMode(next: Mode) {
    setMode(next);
    try {
      window.localStorage.setItem(MODE_STORAGE_KEY, next);
    } catch {
      // A browser refusing storage is not a reason to break the bar.
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    if (chatMode) {
      if (!modelId) return;
      onAsk(trimmed);
    } else {
      onAddDirective(trimmed);
    }
    setText("");
  }

  const modeButton = (value: Mode, label: string) => (
    <button
      type="button"
      onClick={() => selectMode(value)}
      aria-pressed={mode === value}
      className={`px-2.5 py-1 font-body text-xs font-semibold transition-colors ${
        mode === value
          ? value === "chat"
            ? "bg-brand-gray text-white"
            : "bg-brand-teal text-white"
          : "text-brand-mid-gray hover:bg-brand-light-gray-2"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="border-t border-brand-light-gray-1 bg-surface/95 backdrop-blur-sm">
      <form onSubmit={handleSubmit} className="flex items-center gap-2 px-4 py-2">
        <div className="flex flex-shrink-0 overflow-hidden rounded-lg border border-brand-light-gray-1">
          {modeButton("chat", "Chat")}
          {modeButton("directive", "Directive")}
        </div>

        <div
          className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg border px-2.5 py-1.5 transition-colors ${
            chatMode
              ? "border-brand-light-gray-1 bg-brand-light-gray-2 focus-within:border-brand-gray"
              : "border-brand-light-gray-1 bg-surface focus-within:border-brand-teal"
          }`}
        >
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={
              disabled
                ? "Post-processing is running..."
                : chatMode
                  ? "Ask this call anything..."
                  : "e.g. Ask about their cloud migration timeline..."
            }
            disabled={disabled}
            aria-label={chatMode ? "Ask this call a question" : "Add a directive"}
            className="min-w-0 flex-1 bg-transparent font-body text-sm text-brand-dark-gray placeholder:text-brand-mid-gray focus:outline-none"
          />
          {asking && (
            <span className="flex-shrink-0 font-mono text-[10px] uppercase tracking-wider text-brand-mid-gray">
              Reading the call...
            </span>
          )}
          {text.trim() && !asking && (
            <span className="flex-shrink-0 font-mono text-[10px] text-brand-mid-gray" aria-hidden="true">
              &#8629;
            </span>
          )}
          {chatMode && (
            <ModelChip models={models} value={modelId} localOnly={localOnly} onChange={onModelChange} />
          )}
        </div>
      </form>
    </div>
  );
}
