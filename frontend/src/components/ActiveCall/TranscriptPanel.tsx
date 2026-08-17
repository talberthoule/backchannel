import { useEffect, useRef } from "react";
import type { Speaker, TranscriptEntry } from "../../types";

interface TranscriptPanelProps {
  transcripts: TranscriptEntry[];
  speakers: Speaker[];
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

const PANEL_ID = "live-transcription-panel";

export default function TranscriptPanel({ transcripts, speakers, collapsed = false, onToggleCollapse }: TranscriptPanelProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const shouldAutoScrollRef = useRef(true);

  useEffect(() => {
    if (shouldAutoScrollRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [transcripts]);

  function handleScroll() {
    const container = scrollContainerRef.current;
    if (!container) return;

    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    shouldAutoScrollRef.current = distanceFromBottom < 64;
  }

  function formatTimestamp(ts: string): string {
    try {
      const date = new Date(ts);
      return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch {
      return ts;
    }
  }

  function speakerLabel(entry: TranscriptEntry, speaker: Speaker | null): string {
    if (speaker) {
      return speaker.display_name && speaker.display_name_enabled
        ? speaker.display_name
        : speaker.name;
    }
    return entry.id ? "Unknown" : "Live";
  }

  function speakerColor(entry: TranscriptEntry, speaker: Speaker | null): string {
    if (speaker) return speaker.color;
    return entry.id ? "#64748b" : "#2dd4bf";
  }

  // The last entry may be interim (in-progress speech) — detect by checking
  // if it's very recent (within 2s) and there's more than one entry
  const isLastInterim = (i: number) => {
    if (i !== transcripts.length - 1) return false;
    if (transcripts.length < 2) return false;
    const now = Date.now();
    const ts = new Date(transcripts[i].timestamp).getTime();
    return now - ts < 2000;
  };

  // Collapsed: a rail on desktop, a single bar on mobile. The transcript keeps
  // arriving; it just stops taking a column of the call screen.
  if (collapsed) {
    return (
      <div className="flex h-full w-full items-center gap-2 px-2 py-2 md:flex-col md:justify-start md:gap-3 md:py-3">
        <button
          type="button"
          onClick={onToggleCollapse}
          aria-expanded={false}
          aria-controls={PANEL_ID}
          title="Show live transcription"
          className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md text-brand-mid-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-teal focus:ring-2 focus:ring-brand-teal-light"
        >
          <svg className="h-4 w-4 -rotate-90 md:rotate-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="m15 19-7-7 7-7" />
          </svg>
        </button>
        <span className="font-display text-xs font-semibold uppercase tracking-wide text-brand-teal md:[writing-mode:vertical-rl]">
          Live Transcription
        </span>
        {transcripts.length > 0 && (
          <span className="font-mono text-[11px] tabular-nums text-brand-mid-gray">
            {transcripts.length}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col" id={PANEL_ID}>
      <div className="flex items-start justify-between gap-2 border-b border-brand-light-gray-1 px-4 pb-3">
        <h3 className="font-display text-sm font-semibold uppercase tracking-wide text-brand-teal">
          Live Transcription
        </h3>
        {onToggleCollapse && (
          <button
            type="button"
            onClick={onToggleCollapse}
            aria-expanded
            aria-controls={PANEL_ID}
            title="Hide live transcription"
            className="-mt-1 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md text-brand-mid-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-teal focus:ring-2 focus:ring-brand-teal-light"
          >
            <svg className="h-4 w-4 rotate-90 md:rotate-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="m9 5 7 7-7 7" />
            </svg>
          </button>
        )}
      </div>

      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 overflow-y-auto p-4"
      >
        {transcripts.length === 0 ? (
          <p className="py-8 text-center font-body text-sm text-brand-mid-gray">
            Waiting for speech...
          </p>
        ) : (
          <div className="space-y-3">
            {transcripts.map((entry, i) => {
              const isMarker = entry.text.startsWith("---");
              const interim = isLastInterim(i);

              if (isMarker) {
                return (
                  <div key={i} className="text-center py-2">
                    <span className="text-xs font-medium text-brand-amber bg-orange-50 px-3 py-1 rounded-full">
                      {entry.text}
                    </span>
                  </div>
                );
              }

              const speaker = entry.speaker_id ? speakers.find((s) => s.id === entry.speaker_id) : null;
              const label = speakerLabel(entry, speaker ?? null);
              const color = speakerColor(entry, speaker ?? null);

              return (
                <div key={i} className={`${interim ? "opacity-50" : ""}`}>
                  <span className="mr-2 font-mono text-xs text-brand-mid-gray">
                    {formatTimestamp(entry.timestamp)}
                  </span>
                  <span
                    className="mr-1.5 inline-block max-w-24 truncate rounded px-1.5 py-0.5 align-middle text-[10px] font-semibold text-white"
                    style={{ backgroundColor: color }}
                    title={label}
                  >
                    {label}
                  </span>
                  <span className={`font-body text-sm leading-relaxed ${
                    interim ? "text-brand-mid-gray italic" : "text-brand-dark-gray"
                  }`}>
                    {entry.text}
                    {interim && <span className="animate-pulse ml-1">|</span>}
                  </span>
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </div>
  );
}
