import { memo, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { Speaker, TranscriptEntry } from "../../types";
import { findTranscriptMatches } from "./transcriptSearch";
import TranscriptRow from "./TranscriptRow";

interface TranscriptPanelProps {
  transcripts: TranscriptEntry[];
  speakers: Speaker[];
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

const PANEL_ID = "live-transcription-panel";
export const TRANSCRIPT_PAGE_SIZE = 40;

const GHOST_BUTTON =
  "flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md text-brand-mid-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-teal focus:ring-2 focus:ring-brand-teal-light disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-brand-mid-gray";

export default memo(function TranscriptPanel({ transcripts, speakers, collapsed = false, onToggleCollapse }: TranscriptPanelProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const shouldAutoScrollRef = useRef(true);
  const resetScrollRef = useRef(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Search over the transcript. Hidden behind a quiet magnifier (or Ctrl+F
  // with the panel focused) so the call screen keeps the bareness ALP-305
  // fought for, and one click away when a name or number needs finding
  // mid-call.
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [current, setCurrent] = useState(0);
  // null follows the most recent 40 entries; a number holds a history window.
  const [historyStart, setHistoryStart] = useState<number | null>(null);
  const speakerById = useMemo(() => new Map(speakers.map(s => [s.id, s])), [speakers]);

  const searchActive = searchOpen && query.trim().length > 0;
  const matches = useMemo(
    () => (searchActive ? findTranscriptMatches(transcripts, query) : []),
    [searchActive, transcripts, query],
  );
  const matchesRef = useRef(matches);
  matchesRef.current = matches;
  const currentClamped = Math.min(current, Math.max(0, matches.length - 1));
  const activeMatch = searchActive ? matches[currentClamped] : undefined;
  const latestStart = Math.max(0, transcripts.length - TRANSCRIPT_PAGE_SIZE);
  const visibleStart = activeMatch !== undefined
    ? Math.min(Math.floor(activeMatch / TRANSCRIPT_PAGE_SIZE) * TRANSCRIPT_PAGE_SIZE, latestStart)
    : Math.min(historyStart ?? latestStart, latestStart);
  const visibleEntries = transcripts.slice(visibleStart, visibleStart + TRANSCRIPT_PAGE_SIZE);

  useEffect(() => {
    if (historyStart !== null && historyStart > latestStart) setHistoryStart(latestStart);
  }, [historyStart, latestStart]);

  useEffect(() => {
    // While a search is underway the view holds its place instead of
    // following new speech; closing the search resumes the live tail.
    if (searchActive || collapsed) return;
    const container = scrollContainerRef.current;
    if (container && historyStart === null && shouldAutoScrollRef.current) {
      // Interim messages arrive frequently: no repeated smooth-scroll animation.
      container.scrollTop = container.scrollHeight;
    }
  }, [transcripts, searchActive, historyStart, collapsed]);

  useEffect(() => {
    if (resetScrollRef.current && !searchActive && historyStart !== null && scrollContainerRef.current) {
      scrollContainerRef.current.scrollTop = 0;
    }
    resetScrollRef.current = false;
  }, [historyStart, searchActive]);

  // Keep the pointer valid as matches appear and disappear live.
  useEffect(() => {
    if (current >= matches.length) setCurrent(Math.max(0, matches.length - 1));
  }, [matches.length, current]);

  // Bring the active match into view on navigation or a new query - but not
  // on every arriving transcript entry, which would yank the view around.
  useEffect(() => {
    if (activeMatch === undefined || collapsed) return;
    const el = scrollContainerRef.current?.querySelector(
      `[data-entry-index="${activeMatch}"]`,
    );
    el?.scrollIntoView({ block: "center" });
  }, [activeMatch, visibleStart, query, collapsed]);

  function openSearch() {
    setSearchOpen(true);
    // The input autofocuses on mount; a repeat Ctrl+F reselects its text.
    searchInputRef.current?.select();
  }

  function closeSearch() {
    setSearchOpen(false);
    setQuery("");
    setCurrent(0);
    shouldAutoScrollRef.current = true;
    setHistoryStart(null);
  }

  function gotoMatch(delta: number) {
    const m = matchesRef.current;
    if (!m.length) return;
    setCurrent((value) => (Math.min(value, m.length - 1) + delta + m.length) % m.length);
  }

  function handlePanelKeyDown(event: KeyboardEvent<HTMLElement>) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f") {
      event.preventDefault();
      openSearch();
    } else if (event.key === "Escape" && searchOpen) {
      event.preventDefault();
      closeSearch();
    }
  }

  function handleSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      gotoMatch(event.shiftKey ? -1 : 1);
    }
  }

  // Follow the tail only while the user is already near it.
  function handleScroll() {
    const container = scrollContainerRef.current;
    if (!container || searchActive) return;
    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    shouldAutoScrollRef.current = distanceFromBottom < 64;
    if (!shouldAutoScrollRef.current && historyStart === null) setHistoryStart(visibleStart);
    if (shouldAutoScrollRef.current && visibleStart === latestStart) setHistoryStart(null);
  }

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
    <div className="flex h-full min-h-0 flex-col" id={PANEL_ID} onKeyDown={handlePanelKeyDown}>
      <div className="flex shrink-0 items-start justify-between gap-2 border-b border-brand-light-gray-1 px-4 pb-3">
        {searchOpen ? (
          <div className="-mt-1 flex min-w-0 flex-1 items-center gap-1.5">
            <input
              ref={searchInputRef}
              autoFocus
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setCurrent(0);
              }}
              onKeyDown={handleSearchKeyDown}
              placeholder="Search transcript"
              aria-label="Search live transcript"
              className="min-w-0 flex-1 rounded-md border border-brand-light-gray-1 bg-surface px-2 py-1 font-body text-sm text-brand-dark-gray placeholder:text-brand-mid-gray focus:border-brand-teal focus:outline-none"
            />
            <span aria-live="polite" className="flex-shrink-0 font-mono text-[11px] tabular-nums text-brand-mid-gray">
              {matches.length > 0 ? `${currentClamped + 1}/${matches.length}` : searchActive ? "0" : ""}
            </span>
            <button
              type="button"
              onClick={() => gotoMatch(-1)}
              disabled={matches.length === 0}
              title="Previous match (Shift+Enter)"
              aria-label="Previous match"
              className={GHOST_BUTTON}
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="m18 15-6-6-6 6" />
              </svg>
            </button>
            <button
              type="button"
              onClick={() => gotoMatch(1)}
              disabled={matches.length === 0}
              title="Next match (Enter)"
              aria-label="Next match"
              className={GHOST_BUTTON}
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="m6 9 6 6 6-6" />
              </svg>
            </button>
            <button
              type="button"
              onClick={closeSearch}
              title="Close search (Esc)"
              aria-label="Close transcript search"
              className={GHOST_BUTTON}
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        ) : (
          <>
            <h3 className="font-display text-sm font-semibold uppercase tracking-wide text-brand-teal">
              Live Transcription
            </h3>
            <div className="-mt-1 flex flex-shrink-0 items-start gap-1">
              <button
                type="button"
                onClick={openSearch}
                title="Search transcript (Ctrl+F)"
                aria-label="Search live transcript"
                className={GHOST_BUTTON}
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} aria-hidden="true">
                  <circle cx="11" cy="11" r="7" />
                  <path strokeLinecap="round" d="m20 20-3.5-3.5" />
                </svg>
              </button>
              {onToggleCollapse && (
                <button
                  type="button"
                  onClick={onToggleCollapse}
                  aria-expanded
                  aria-controls={PANEL_ID}
                  title="Hide live transcription"
                  className={GHOST_BUTTON}
                >
                  <svg className="h-4 w-4 rotate-90 md:rotate-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" d="m9 5 7 7-7 7" />
                  </svg>
                </button>
              )}
            </div>
          </>
        )}
      </div>

      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        tabIndex={0}
        role="region"
        aria-label="Live transcription entries"
        className="min-h-0 flex-1 overflow-y-auto p-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal-light"
      >
        {transcripts.length === 0 ? (
          <p className="py-8 text-center font-body text-sm text-brand-mid-gray">
            Waiting for speech...
          </p>
        ) : (
          <div className="space-y-3">
            {visibleEntries.map((entry, offset) => {
              const index = visibleStart + offset;
              return (
                <TranscriptRow
                  key={entry.interim ? "interim" : entry.id ?? `entry-${entry.sequence ?? index}`}
                  entry={entry}
                  index={index}
                  speaker={entry.speaker_id ? speakerById.get(entry.speaker_id) : undefined}
                  query={searchActive ? query : ""}
                  currentMatch={activeMatch === index}
                />
              );
            })}
          </div>
        )}
      </div>
      {transcripts.length > TRANSCRIPT_PAGE_SIZE && !searchActive && (
        <nav aria-label="Transcript pages" className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-brand-light-gray-1 px-4 py-2">
          <span role="status" className="font-body text-sm tabular-nums text-brand-gray">
            {visibleStart + 1}-{Math.min(visibleStart + TRANSCRIPT_PAGE_SIZE, transcripts.length)} of {transcripts.length} entries
          </span>
          <div className="flex items-center gap-1">
            {[
              { label: "First", target: 0, disabled: visibleStart === 0 },
              { label: "Older", target: Math.max(0, visibleStart - TRANSCRIPT_PAGE_SIZE), disabled: visibleStart === 0 },
              { label: "Newer", target: Math.min(latestStart, visibleStart + TRANSCRIPT_PAGE_SIZE), disabled: visibleStart === latestStart },
              { label: "Live", target: latestStart, disabled: historyStart === null },
            ].map(({ label, target, disabled }) => (
              <button
                key={label}
                type="button"
                aria-label={`${label} transcript entries`}
                disabled={disabled}
                onClick={() => {
                  const follow = target === latestStart;
                  resetScrollRef.current = !follow;
                  shouldAutoScrollRef.current = follow;
                  setHistoryStart(follow ? null : target);
                }}
                className="min-h-11 rounded-md px-2 font-body text-sm text-brand-dark-gray hover:bg-brand-light-gray-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-teal disabled:cursor-not-allowed disabled:opacity-40"
              >
                {label}
              </button>
            ))}
          </div>
        </nav>
      )}
    </div>
  );
});
