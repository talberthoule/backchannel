import { useState } from "react";

interface DirectiveBarProps {
  onAddDirective: (text: string) => void;
  disabled?: boolean;
}

export default function DirectiveBar({ onAddDirective, disabled = false }: DirectiveBarProps) {
  const [expanded, setExpanded] = useState(false);
  const [text, setText] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    onAddDirective(trimmed);
    setText("");
    setExpanded(false);
  }

  return (
    <div className="border-t border-brand-light-gray-1 bg-white/95 backdrop-blur-sm">
      {expanded ? (
        <form onSubmit={handleSubmit} className="flex items-center gap-3 px-4 py-3">
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={disabled ? "Post-processing is running..." : "e.g. Ask about their cloud migration timeline..."}
            autoFocus
            disabled={disabled}
            className="flex-1 rounded-lg border border-brand-light-gray-1 px-3 py-2 font-body text-sm text-brand-dark-gray placeholder:text-brand-mid-gray focus:border-brand-teal focus:outline-none focus:ring-1 focus:ring-brand-teal"
          />
          <button
            type="submit"
            disabled={disabled || !text.trim()}
            className="rounded-lg bg-brand-teal px-4 py-2 font-body text-sm font-medium text-white transition-colors hover:bg-brand-teal-dark disabled:opacity-40"
          >
            Add
          </button>
          <button
            type="button"
            onClick={() => {
              setExpanded(false);
              setText("");
            }}
            className="rounded-lg px-3 py-2 font-body text-sm text-brand-gray transition-colors hover:bg-brand-light-gray-2"
          >
            Cancel
          </button>
        </form>
      ) : (
        <div className="flex items-center px-4 py-2">
          <button
            onClick={() => {
              if (!disabled) setExpanded(true);
            }}
            disabled={disabled}
            className="flex items-center gap-2 rounded-lg px-3 py-1.5 font-body text-sm font-medium text-brand-teal transition-colors hover:bg-brand-light-gray-2 disabled:cursor-not-allowed disabled:text-brand-mid-gray disabled:hover:bg-transparent"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            Add Directive
          </button>
        </div>
      )}
    </div>
  );
}
