import { memo } from "react";
import type { Speaker, TranscriptEntry } from "../../types";
import { highlightParts } from "./transcriptSearch";

const timeFormatter = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit", minute: "2-digit", second: "2-digit",
});

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? timestamp : timeFormatter.format(date);
}

interface TranscriptRowProps {
  entry: TranscriptEntry;
  index: number;
  speaker?: Speaker;
  query: string;
  currentMatch: boolean;
}

// Stable saved entries skip rendering when only the interim tail changes.
export default memo(function TranscriptRow({ entry, index, speaker, query, currentMatch }: TranscriptRowProps) {
  if (entry.text.startsWith("---")) {
    return (
      <div data-entry-index={index} className="text-center py-2">
        <span className="text-xs font-medium text-brand-amber bg-orange-50 px-3 py-1 rounded-full">
          {entry.text}
        </span>
      </div>
    );
  }

  const interim = entry.interim === true;
  const label = speaker
    ? speaker.display_name && speaker.display_name_enabled ? speaker.display_name : speaker.name
    : entry.id ? "Unknown" : "Live";
  const color = speaker?.color ?? (entry.id ? "#64748b" : "#2dd4bf");

  return (
    <div data-entry-index={index} className={`${interim ? "opacity-50" : ""} ${
      currentMatch ? "-mx-2 rounded-md bg-brand-teal/5 px-2 py-1 ring-1 ring-brand-teal/20" : ""
    }`}>
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
      <span className={`font-body text-sm leading-relaxed ${interim ? "text-brand-mid-gray italic" : "text-brand-dark-gray"}`}>
        {query
          ? highlightParts(entry.text, query).map((part, k) =>
            part.hit
              ? <mark key={k} className="rounded-sm bg-amber-200 text-brand-dark-gray">{part.text}</mark>
              : <span key={k}>{part.text}</span>,
          )
          : entry.text}
        {interim && <span className="animate-pulse motion-reduce:animate-none ml-1">|</span>}
      </span>
    </div>
  );
});
