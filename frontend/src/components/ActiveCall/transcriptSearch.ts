import type { TranscriptEntry } from "../../types";

// Search over the live transcript: plain, literal, case-insensitive
// substring matching. Kept out of the component so the matching rules are
// unit-testable without rendering.

// Indices of the transcript entries whose text contains the query.
export function findTranscriptMatches(transcripts: TranscriptEntry[], query: string): number[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const hits: number[] = [];
  transcripts.forEach((entry, index) => {
    if ((entry.text || "").toLowerCase().includes(q)) hits.push(index);
  });
  return hits;
}

export interface HighlightPart {
  text: string;
  hit: boolean;
}

// Split an entry's text into parts, marking the case-insensitive occurrences
// of the query. Regex metacharacters in the query are treated literally, so
// searching for "$1.2M (approx)" finds exactly that.
export function highlightParts(text: string, query: string): HighlightPart[] {
  const q = query.trim();
  if (!q) return [{ text, hit: false }];
  const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return text
    .split(new RegExp(`(${escaped})`, "ig"))
    .filter((part) => part !== "")
    .map((part) => ({ text: part, hit: part.toLowerCase() === q.toLowerCase() }));
}
