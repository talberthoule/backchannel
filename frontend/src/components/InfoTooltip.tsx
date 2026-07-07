import { useEffect, useRef, useState } from "react";

interface Props {
  /** Primary explanation shown in the popover body */
  content: string;
  /** Optional bullet points shown below the main content */
  details?: string[];
  /** Popover preferred placement — flips automatically if clipped */
  placement?: "right" | "bottom";
}

export default function InfoTooltip({ content, details, placement = "right" }: Props) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const hoverTimeout = useRef<ReturnType<typeof setTimeout>>();
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const [actualPlacement, setActualPlacement] = useState(placement);

  // Position the popover relative to the trigger
  useEffect(() => {
    if (!open || !triggerRef.current) return;

    const rect = triggerRef.current.getBoundingClientRect();
    const popoverWidth = 320;
    const popoverEstHeight = 160;
    const gap = 8;

    let top: number;
    let left: number;
    let place = placement;

    if (placement === "right") {
      top = rect.top + rect.height / 2 - popoverEstHeight / 2;
      left = rect.right + gap;
      // Flip to bottom if clipped on the right
      if (left + popoverWidth > window.innerWidth - 16) {
        place = "bottom";
      }
    }

    if (place === "bottom") {
      top = rect.bottom + gap;
      left = rect.left - popoverWidth / 2 + rect.width / 2;
      // Keep within viewport
      if (left < 16) left = 16;
      if (left + popoverWidth > window.innerWidth - 16) left = window.innerWidth - 16 - popoverWidth;
    } else {
      top = rect.top + rect.height / 2 - popoverEstHeight / 2;
      left = rect.right + gap;
    }

    // Vertical bounds
    if (top < 16) top = 16;

    setActualPlacement(place);
    setPos({ top, left });
  }, [open, placement]);

  // Close on click outside
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        popoverRef.current && !popoverRef.current.contains(e.target as Node) &&
        triggerRef.current && !triggerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open]);

  const show = () => {
    clearTimeout(hoverTimeout.current);
    setOpen(true);
  };

  const hide = () => {
    hoverTimeout.current = setTimeout(() => setOpen(false), 200);
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        onMouseEnter={show}
        onMouseLeave={hide}
        className="inline-flex items-center justify-center h-4 w-4 rounded-full border border-brand-light-gray-1 text-brand-mid-gray hover:border-brand-teal hover:text-brand-teal hover:bg-brand-teal/5 transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-brand-teal-light/40"
        aria-label="More info"
      >
        <svg className="h-2.5 w-2.5" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0ZM8.94 6.94a.75.75 0 1 1-1.061-1.061 .75.75 0 0 1 1.06 1.06ZM10 8.75a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5a.75.75 0 0 1 .75-.75Z" clipRule="evenodd" />
        </svg>
      </button>

      {open && pos && (
        <div
          ref={popoverRef}
          onMouseEnter={show}
          onMouseLeave={hide}
          className={`fixed z-50 w-80 rounded-xl border border-brand-light-gray-1 bg-white shadow-xl ring-1 ring-black/5 animate-in fade-in duration-150 ${
            actualPlacement === "bottom" ? "origin-top" : "origin-left"
          }`}
          style={{ top: pos.top, left: pos.left }}
        >
          {/* Blue accent bar */}
          <div className="h-1 rounded-t-xl bg-gradient-to-r from-brand-teal to-brand-teal-light" />

          <div className="px-4 py-3">
            <p className="font-body text-sm leading-relaxed text-brand-dark-gray">
              {content}
            </p>

            {details && details.length > 0 && (
              <ul className="mt-2.5 space-y-1.5">
                {details.map((item, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-brand-gray">
                    <span className="mt-1 h-1 w-1 flex-shrink-0 rounded-full bg-brand-teal/50" />
                    <span className="font-body leading-relaxed">{item}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </>
  );
}
