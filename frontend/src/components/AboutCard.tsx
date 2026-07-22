import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ReleaseNote } from "../types";
import * as api from "../services/api";

interface AboutCardProps {
  version: string | null;
  // Version last seen by this browser before an upgrade; releases newer than
  // it get a "New" badge. Null when there is nothing unread.
  highlightSince?: string | null;
}

// True when a is a strictly newer semver than b; malformed input sorts as 0.
function isNewerVersion(a: string, b: string): boolean {
  const parse = (v: string) => v.split(".").map((p) => parseInt(p, 10) || 0);
  const [pa, pb] = [parse(a), parse(b)];
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const diff = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (diff !== 0) return diff > 0;
  }
  return false;
}

// Admin -> About tab: current version plus the in-app release-notes history
// served by /api/meta/release-notes (newest first, newest expanded).
export default function AboutCard({ version, highlightSince }: AboutCardProps) {
  const [notes, setNotes] = useState<ReleaseNote[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [expandedVersion, setExpandedVersion] = useState<string | null>(null);

  useEffect(() => {
    api.listReleaseNotes()
      .then((n) => {
        setNotes(n);
        setExpandedVersion(n[0]?.version ?? null);
      })
      .catch((err) => {
        console.error("Failed to load release notes", err);
        setFailed(true);
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-surface p-5 shadow-sm ring-1 ring-brand-light-gray-1/60">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="font-display text-base font-bold text-brand-dark-gray">Backchannel</h2>
            <p className="mt-0.5 font-body text-xs text-brand-gray">
              Real-time meeting analysis: live transcription, speaker attribution, and insight agents.
            </p>
          </div>
          <span className="rounded-full bg-brand-teal/10 px-3 py-1 font-mono text-sm font-semibold text-brand-teal">
            {version ? `v${version}` : "version unavailable"}
          </span>
        </div>
      </div>

      <section>
        <div className="mb-3">
          <h2 className="font-display text-sm font-bold uppercase tracking-wider text-brand-mid-gray">Release Notes</h2>
          <p className="mt-0.5 font-body text-xs text-brand-mid-gray">What changed in each version, newest first.</p>
        </div>

        {loading && (
          <p className="font-body text-sm text-brand-mid-gray">Loading release notes...</p>
        )}
        {failed && (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 font-body text-xs text-amber-900">
            Release notes could not be loaded. The rest of the app is unaffected.
          </p>
        )}

        <div className="space-y-2">
          {notes.map((note) => {
            const expanded = expandedVersion === note.version;
            const isCurrent = version !== null && note.version === version;
            const isUnread = !!highlightSince && isNewerVersion(note.version, highlightSince);
            return (
              <div key={note.version} className="rounded-xl bg-surface shadow-sm ring-1 ring-brand-light-gray-1/60">
                <button
                  type="button"
                  onClick={() => setExpandedVersion(expanded ? null : note.version)}
                  aria-expanded={expanded}
                  className="flex w-full items-center gap-2.5 px-5 py-3 text-left transition-colors hover:bg-brand-light-gray-2/60"
                >
                  <svg className={`h-3 w-3 shrink-0 text-brand-mid-gray transition-transform ${expanded ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                  </svg>
                  <span className="font-mono text-xs font-semibold text-brand-dark-gray">v{note.version}</span>
                  {isCurrent && (
                    <span className="rounded-full bg-brand-teal/10 px-2 py-0.5 font-body text-[10px] font-medium text-brand-teal">
                      Current
                    </span>
                  )}
                  {isUnread && (
                    <span className="rounded-full bg-brand-teal px-2 py-0.5 font-body text-[10px] font-semibold text-white" title={`Released since v${highlightSince}`}>
                      New
                    </span>
                  )}
                  <span className="min-w-0 flex-1 truncate font-body text-sm text-brand-gray">{note.title}</span>
                  <span className="shrink-0 font-body text-[11px] text-brand-mid-gray">{note.date}</span>
                </button>
                {expanded && (
                  <div className="border-t border-brand-light-gray-1/70 px-5 py-4 font-body text-sm text-brand-dark-gray">
                    <div className="chat-markdown">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{note.body}</ReactMarkdown>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
