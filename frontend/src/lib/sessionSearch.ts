// Finding a session by what you remember about it: part of its name, the
// group it sits in, or when it happened. Shared so every box that searches
// sessions behaves the same; the session sidebar and the post-call chat
// scope picker both use it.
import type { Session, SessionGroup } from "../types";

export function normalizeQuery(query: string): string {
  return query.trim().toLowerCase();
}

/** The spellings of one calendar date a person might type into the find box.
 *
 *  A session carries no visible date tag; these are derived from its
 *  timestamps and matched by prefix, so "october", "oct 8", "8", "08", "8-",
 *  "8/", "10/8", "10-08" and "2026-10-08" all find a call held on 8 October
 *  2026. Dates are rendered in the viewer's local time zone, the same clock
 *  the sidebar shows. */
export function dateSearchTerms(iso: string | null | undefined): string[] {
  if (!iso) return [];
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return [];
  const monthLong = date.toLocaleDateString("en-US", { month: "long" }).toLowerCase();
  const monthShort = monthLong.slice(0, 3);
  const weekday = date.toLocaleDateString("en-US", { weekday: "long" }).toLowerCase();
  const month = date.getMonth() + 1;
  const day = date.getDate();
  const year = date.getFullYear();
  const mm = String(month).padStart(2, "0");
  const dd = String(day).padStart(2, "0");
  const yy = String(year).slice(-2);
  return Array.from(new Set([
    monthLong, monthShort, weekday, weekday.slice(0, 3), String(year),
    String(day), dd,
    `${month}/${day}`, `${mm}/${dd}`, `${month}/${dd}`,
    `${month}-${day}`, `${mm}-${dd}`, `${month}-${dd}`,
    `${month}/${day}/${year}`, `${mm}/${dd}/${year}`, `${month}/${day}/${yy}`,
    `${month}-${day}-${year}`, `${mm}-${dd}-${year}`, `${year}-${mm}-${dd}`,
    `${monthLong} ${day}`, `${monthShort} ${day}`, `${monthLong} ${dd}`, `${monthShort} ${dd}`,
    `${monthShort}-${day}`, `${monthShort} ${day}, ${year}`, `${monthLong} ${day}, ${year}`,
    `${day} ${monthLong}`, `${day} ${monthShort}`, `${day}-${monthShort}`, `${dd}-${monthShort}`,
  ]));
}

/** Hidden search metadata for one session: the date it was created and, when
 *  different, the date the call started. */
export function sessionSearchTerms(session: Pick<Session, "created_at" | "started_at">): string[] {
  return Array.from(new Set([...dateSearchTerms(session.created_at), ...dateSearchTerms(session.started_at)]));
}

/** Sessions whose name or group name contains the query, case-insensitively,
 *  or whose creation or start date is spelled by it (see dateSearchTerms).
 *  An empty query returns the list untouched. */
export function filterSessions(sessions: Session[], groups: SessionGroup[], query: string): Session[] {
  const needle = normalizeQuery(query);
  if (!needle) return sessions;
  const groupNames = new Map(groups.map((g) => [g.id, g.name.toLowerCase()]));
  return sessions.filter((session) => {
    if (session.name.toLowerCase().includes(needle)) return true;
    const groupName = session.group_id ? groupNames.get(session.group_id) : undefined;
    if (groupName && groupName.includes(needle)) return true;
    return sessionSearchTerms(session).some((term) => term.startsWith(needle));
  });
}
