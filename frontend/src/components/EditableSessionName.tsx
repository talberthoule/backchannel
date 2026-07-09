import { useEffect, useRef, useState } from "react";

interface Props {
  name: string;
  onRename: (newName: string) => Promise<void>;
  className?: string;
  /** Compact mode for sidebar — smaller text, no pencil icon */
  compact?: boolean;
}

export default function EditableSessionName({ name, onRename, className = "", compact = false }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setDraft(name); }, [name]);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const commit = async () => {
    const trimmed = draft.trim();
    setEditing(false);
    if (trimmed && trimmed !== name) {
      await onRename(trimmed);
    } else {
      setDraft(name);
    }
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") { setDraft(name); setEditing(false); }
        }}
        className={`bg-transparent border-b-2 border-brand-teal ${compact ? "text-sm font-medium" : "text-2xl font-bold font-display"} ${className}`}
        autoFocus
      />
    );
  }

  if (compact) {
    return (
      <span
        className={`cursor-pointer truncate block ${className}`}
        onDoubleClick={() => setEditing(true)}
        title="Double-click to rename"
      >
        {name}
      </span>
    );
  }

  return (
    <div className="group flex items-center gap-2">
      <h1 className={`font-display text-2xl font-bold ${className}`}>
        {name}
      </h1>
      <button
        onClick={() => setEditing(true)}
        className="rounded p-1 text-brand-mid-gray opacity-0 group-hover:opacity-100 hover:bg-brand-light-gray-2 hover:text-brand-dark-gray transition-all"
        title="Rename session"
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125" />
        </svg>
      </button>
    </div>
  );
}
