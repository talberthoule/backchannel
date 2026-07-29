import { useEffect, useRef, useState } from "react";
import type { ModelInfo } from "../../types";
import { groupModels, optionLabel, optionState, runsLocally } from "../../lib/modelOptions";

interface ModelChipProps {
  models: ModelInfo[];
  value: string;
  localOnly: boolean;
  onChange: (id: string) => void;
}

/** Model selection for the ask bar.
 *
 * Rendered as metadata rather than a control: borderless at rest so it does not
 * add chrome to a bar that has to stay quiet during a call, bordered on hover
 * and while open. The admission rules come from lib/modelOptions so this agrees
 * with every other picker in the app about what Privacy First allows.
 */
export default function ModelChip({ models, value, localOnly, onChange }: ModelChipProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  const selected = models.find((m) => m.id === value);

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  return (
    <div className="relative flex-shrink-0" ref={ref}>
      <button
        type="button"
        ref={buttonRef}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Model that answers your questions"
        className={`flex items-center gap-1.5 rounded border px-1.5 py-0.5 font-mono text-[10px] transition-colors ${
          open
            ? "border-brand-light-gray-1 bg-surface text-brand-gray"
            : "border-transparent text-brand-mid-gray hover:border-brand-light-gray-1 hover:bg-surface hover:text-brand-gray"
        }`}
      >
        <span
          className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${
            selected && runsLocally(selected) ? "bg-brand-teal" : "border border-brand-amber"
          }`}
          aria-hidden="true"
        />
        {selected?.name || "Select model"}
        <span aria-hidden="true">&#9662;</span>
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute bottom-full right-0 z-30 mb-2 max-h-72 w-64 overflow-y-auto rounded-lg border border-brand-light-gray-1 bg-surface p-1 shadow-lg"
        >
          {groupModels(models).map((group) => (
            <div key={group.provider}>
              <div className="px-2 py-1.5 font-mono text-[9px] uppercase tracking-wider text-brand-mid-gray">
                {group.provider}
              </div>
              {group.models.map((model) => {
                const { locked, suffix } = optionState(model, value, localOnly);
                return (
                  <button
                    key={model.id}
                    type="button"
                    role="option"
                    aria-selected={model.id === value}
                    disabled={locked}
                    title={locked ? `${optionLabel(model)}${suffix}` : optionLabel(model)}
                    onClick={() => {
                      onChange(model.id);
                      setOpen(false);
                      buttonRef.current?.focus();
                    }}
                    className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left font-body text-xs transition-colors ${
                      locked
                        ? "cursor-not-allowed text-brand-mid-gray"
                        : model.id === value
                          ? "bg-brand-light-gray-2 font-semibold text-brand-dark-gray"
                          : "text-brand-dark-gray hover:bg-brand-light-gray-2"
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${
                        locked
                          ? "bg-brand-light-gray-1"
                          : runsLocally(model)
                            ? "bg-brand-teal"
                            : "border border-brand-amber"
                      }`}
                      aria-hidden="true"
                    />
                    <span className="min-w-0 truncate">{model.name}</span>
                    {locked && (
                      <span className="ml-auto flex-shrink-0 font-mono text-[9px] uppercase text-brand-mid-gray">
                        {suffix.includes("api key") ? "no key" : "cloud"}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
