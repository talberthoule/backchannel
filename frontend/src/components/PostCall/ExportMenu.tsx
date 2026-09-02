import { useEffect, useRef, useState } from "react";

// The post-call Export menu: click to open; Escape or a click elsewhere
// closes it, and so does focus leaving it, so keyboard and touch users can
// reach every download link.
export default function ExportMenu({ sessionId }: { sessionId: string }) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const itemClass = "block px-4 py-2.5 text-sm text-brand-dark-gray hover:bg-brand-light-gray-2";

  return (
    <div
      ref={menuRef}
      className="relative"
      onBlur={(event) => {
        if (!menuRef.current?.contains(event.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="post-call-export-menu"
        className="bc-accent-text rounded-lg border border-brand-light-gray-1 px-4 py-2 text-sm font-medium transition-colors hover:bg-brand-light-gray-2"
      >
        Export
      </button>
      <div
        id="post-call-export-menu"
        role="menu"
        aria-label="Export formats"
        className={`absolute right-0 top-full z-10 mt-1 w-48 rounded-lg border border-brand-light-gray-1 bg-surface shadow-lg transition-opacity ${
          open ? "visible opacity-100" : "invisible opacity-0"
        }`}
      >
        <a
          role="menuitem"
          tabIndex={open ? 0 : -1}
          onClick={() => setOpen(false)}
          href={`/api/sessions/${sessionId}/artifacts/summary-export`}
          className={`rounded-t-lg ${itemClass}`}
        >
          Full Summary (HTML)
        </a>
        <a
          role="menuitem"
          tabIndex={open ? 0 : -1}
          onClick={() => setOpen(false)}
          href={`/api/sessions/${sessionId}/artifacts/questions-export`}
          className={itemClass}
        >
          Insights (Excel)
        </a>
        <a
          role="menuitem"
          tabIndex={open ? 0 : -1}
          onClick={() => setOpen(false)}
          href={`/api/sessions/${sessionId}/artifacts/transcript-export`}
          className={`rounded-b-lg ${itemClass}`}
        >
          Transcript (TXT)
        </a>
      </div>
    </div>
  );
}
