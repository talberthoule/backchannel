import { useState, type ReactNode } from "react";
import { ChevronDown, RefreshCw } from "lucide-react";
import type { InsightCluster, Session, SessionSynthesis, SynthesisSectionItem } from "../../types";
import SignalHistory from "../SignalHistory";
import { buildBriefingLayout } from "./briefingSections";

// The briefing is set like a one-page brief: one sheet, a reading measure,
// small-caps section headings on hairline rules, and whitespace instead of
// boxes. The Overview tab carries the stat tiles; this view is for reading.
// Which sections appear, how they pair up, and what the footer says about
// empty ones is decided by buildBriefingLayout in briefingSections.ts.

export { formatList, presentItems, sectionLabels } from "./briefingSections";

interface BriefingViewProps {
  session: Session;
  synthesis: SessionSynthesis | null;
  signalHistoryCount: number;
  onRefresh: () => Promise<void>;
  refreshing: boolean;
  error?: string | null;
}

const MEETING_TYPE_LABELS: Record<string, string> = {
  general: "General meeting",
  client_sales: "Client sales",
  customer_delivery: "Customer delivery",
  internal_enablement: "Internal enablement",
  internal_checkin: "Internal check-in",
  vendor_partner: "Vendor and partner",
};

export function meetingTypeLabel(meetingType: string | undefined): string {
  if (!meetingType) return "";
  return MEETING_TYPE_LABELS[meetingType] || meetingType.replace(/_/g, " ");
}

// A status is quiet text unless it asks for something of the reader: blocked
// or stalled work reads in red with a mark, open or pending work carries an
// amber mark, and settled states (done, won, in progress) stay plain.
export type StatusTone = "blocked" | "open" | "quiet";

export function statusTone(status: string): StatusTone {
  const s = status.toLowerCase();
  if (/(block|stuck|stall|urgent|escalat|overdue|at risk|lost)/.test(s)) return "blocked";
  if (/(open|pending|todo|to do|not started|unresolved|waiting|needs)/.test(s)) return "open";
  return "quiet";
}

export function formatUpdated(value: string | null | undefined): string | null {
  if (!value) return null;
  const time = new Date(value);
  if (!Number.isFinite(time.getTime())) return null;
  return time.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

// Middle dot, built from its code point so the source stays ASCII.
const SEPARATOR = String.fromCharCode(0xb7);

function Separator() {
  return (
    <span aria-hidden="true" className="mx-2 text-brand-light-gray-1">
      {SEPARATOR}
    </span>
  );
}

// Shared with the Overview tab so both surfaces read a status the same way.
export function StatusText({ status }: { status: string }) {
  const tone = statusTone(status);
  if (tone === "quiet") return <span>{status}</span>;
  const mark = tone === "blocked" ? "bg-red-500" : "bg-brand-amber";
  const text = tone === "blocked" ? "font-medium text-red-700 dark:text-red-400" : "font-medium text-brand-gray";
  return (
    <span className={`inline-flex items-center gap-1.5 ${text}`}>
      <span aria-hidden="true" className={`h-1.5 w-1.5 shrink-0 rounded-full ${mark}`} />
      {status}
    </span>
  );
}

// Status before owner, on the title row when there is room and on their own
// line when there is not. Both are plain small text; the only color on the
// row is a status mark that asks for attention.
function ItemMeta({ status, owner }: { status?: string; owner?: string }) {
  if (!status && !owner) return null;
  return (
    <span className="flex shrink-0 flex-wrap items-center font-body text-xs text-brand-mid-gray">
      {status && <StatusText status={status} />}
      {status && owner && <Separator />}
      {owner && <span>{owner}</span>}
    </span>
  );
}

// One affordance for the reasoning behind an item, closed by default so the
// page reads as findings first and argument on request.
function Disclosure({ text }: { text?: string }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <div className="mt-1.5">
      {/* The label stays a quiet line of small text, but the button itself is
          at least 32px tall (44px on touch screens) with the extra height
          folded back through negative margins so the row keeps its rhythm. */}
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        className="-my-2 flex min-h-8 w-fit items-center gap-1 font-body text-xs font-medium text-brand-mid-gray transition-colors hover:text-brand-teal [@media(hover:none)]:min-h-11"
      >
        <ChevronDown
          aria-hidden="true"
          className={`h-3.5 w-3.5 transition-transform motion-reduce:transition-none ${open ? "rotate-180" : ""}`}
        />
        Why this matters
      </button>
      {open && (
        <p className="mt-1.5 max-w-prose font-body text-sm leading-relaxed text-brand-gray">{text}</p>
      )}
    </div>
  );
}

// The list style every section shares: hairline dividers, no boxes. Exported
// with SectionHeading so the Overview tab can set its lists the same way.
export const DIVIDED_LIST_CLASS = "divide-y divide-brand-light-gray-1/60";

// The optional id lands on the h3 so a caller's section can point at it
// with aria-labelledby.
export function SectionHeading({ label, count, id }: { label: string; count?: number; id?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-brand-light-gray-1 pb-2">
      <h3 id={id} className="font-display text-[11px] font-semibold uppercase tracking-[0.12em] text-brand-mid-gray">
        {label}
      </h3>
      {count !== undefined && count > 0 && (
        <span className="font-body text-[11px] font-medium tabular-nums text-brand-mid-gray">{count}</span>
      )}
    </div>
  );
}

// The lead list (top outcomes) uses display type and a hanging numeral; every
// other section uses the same row at body size.
function Item({ item, lead = false, index = 0 }: { item: SynthesisSectionItem; lead?: boolean; index?: number }) {
  const heading = (item.title || "").trim();
  const body = (item.summary || "").trim();
  const title = heading || body;
  const summary = heading && body ? body : "";
  return (
    <li className={`flex items-baseline gap-4 ${lead ? "py-4" : "py-3"} first:pt-0 last:pb-0`}>
      {lead && (
        <span className="bc-accent-text w-5 shrink-0 font-display text-sm font-semibold tabular-nums">
          {index + 1}
        </span>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <p
            className={`min-w-[14rem] flex-1 text-pretty text-brand-dark-gray ${
              lead
                ? "font-display text-lg font-semibold leading-snug tracking-tight"
                : "font-body text-sm font-semibold leading-snug"
            }`}
          >
            {title}
          </p>
          <ItemMeta status={item.status} owner={item.owner} />
        </div>
        {summary && (
          <p className="mt-1 max-w-prose font-body text-sm leading-relaxed text-brand-gray">{summary}</p>
        )}
        <Disclosure text={item.rationale} />
      </div>
    </li>
  );
}

// Items arrive already filtered to readable ones by buildBriefingLayout.
function ItemSection({ label, items, lead = false }: { label: string; items: SynthesisSectionItem[]; lead?: boolean }) {
  if (items.length === 0) return null;
  const rows = items.map((item, index) => (
    <Item key={`${item.title}-${index}`} item={item} lead={lead} index={index} />
  ));
  return (
    <section>
      <SectionHeading label={label} count={items.length} />
      {lead ? (
        <ol className={`mt-4 ${DIVIDED_LIST_CLASS}`}>{rows}</ol>
      ) : (
        <ul className={`mt-4 ${DIVIDED_LIST_CLASS}`}>{rows}</ul>
      )}
    </section>
  );
}

function ClustersSection({ clusters }: { clusters: InsightCluster[] }) {
  if (clusters.length === 0) return null;
  return (
    <section>
      <SectionHeading label="Insight clusters" count={clusters.length} />
      <ul className={`mt-4 ${DIVIDED_LIST_CLASS}`}>
        {clusters.map((cluster) => (
          <li key={cluster.id} className="py-3 first:pt-0 last:pb-0">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <p className="min-w-[14rem] flex-1 text-pretty font-body text-sm font-semibold leading-snug text-brand-dark-gray">
                {cluster.title}
              </p>
              {cluster.confidence && (
                <span className="shrink-0 font-body text-xs text-brand-mid-gray">Confidence: {cluster.confidence}</span>
              )}
            </div>
            {cluster.summary && (
              <p className="mt-1 max-w-prose font-body text-sm leading-relaxed text-brand-gray">{cluster.summary}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ErrorNote({ text }: { text: string }) {
  return (
    <p
      role="alert"
      className="rounded-md border border-red-200 bg-red-50 px-3 py-2 font-body text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-400"
    >
      {text}
    </p>
  );
}

// The context line under the title: meeting type, freshness, and the
// briefing's state only when it is something other than complete.
function contextParts(session: Pick<Session, "meeting_type">, synthesis: SessionSynthesis | null): ReactNode[] {
  const parts: ReactNode[] = [];
  const typeLabel = meetingTypeLabel(session.meeting_type);
  if (typeLabel) parts.push(<span key="type">{typeLabel}</span>);
  if (!synthesis) {
    parts.push(<span key="none">No briefing generated yet</span>);
    return parts;
  }
  const updated = formatUpdated(synthesis.updated_at || synthesis.created_at);
  if (updated) parts.push(<span key="updated">Updated {updated}</span>);
  if (synthesis.status === "partial") {
    parts.push(<span key="status" className="font-medium text-amber-700 dark:text-amber-400">Partial briefing</span>);
  } else if (synthesis.status === "error") {
    parts.push(<span key="status" className="font-medium text-red-700 dark:text-red-400">Briefing failed</span>);
  } else if (synthesis.status === "pending") {
    parts.push(<span key="status">Briefing in progress</span>);
  }
  return parts;
}

export default function BriefingView({ session, synthesis, signalHistoryCount, onRefresh, refreshing, error }: BriefingViewProps) {
  const actionLabel = refreshing
    ? synthesis
      ? "Refreshing..."
      : "Generating..."
    : synthesis
      ? "Refresh Briefing"
      : "Generate Briefing";
  // Generating a missing briefing is the page's one action, so it is the
  // filled button; refreshing an existing one is secondary and stays quiet.
  const buttonClass = synthesis
    ? "border border-brand-light-gray-1 bg-surface font-medium text-brand-gray hover:border-brand-mid-gray hover:text-brand-dark-gray disabled:cursor-wait disabled:opacity-60"
    : "bg-brand-teal font-semibold text-white hover:bg-brand-teal-dark disabled:cursor-wait disabled:bg-brand-mid-gray";

  const context = contextParts(session, synthesis);
  const layout = buildBriefingLayout(session, synthesis);
  const arbiterNotes = synthesis?.arbiter_notes?.trim() || "";
  const clusters = synthesis?.clusters || [];

  return (
    <article className="rounded-xl bg-surface px-5 py-6 shadow-sm sm:px-10 sm:py-8">
      <div className="mx-auto max-w-[52rem] space-y-10">
        <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
          <div className="min-w-0">
            <h2 className="font-display text-xl font-semibold tracking-tight text-brand-dark-gray">
              Conversation briefing
            </h2>
            {context.length > 0 && (
              <p className="mt-1 flex flex-wrap items-center font-body text-sm text-brand-gray">
                {context.map((part, index) => (
                  <span key={index} className="inline-flex items-center">
                    {index > 0 && <Separator />}
                    {part}
                  </span>
                ))}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            className={`inline-flex shrink-0 items-center gap-1.5 rounded-md px-3.5 py-2 font-body text-sm transition-colors ${buttonClass}`}
          >
            <RefreshCw
              aria-hidden="true"
              className={`h-4 w-4 ${refreshing ? "animate-spin motion-reduce:animate-none" : ""}`}
            />
            {actionLabel}
          </button>
        </header>

        {error && <ErrorNote text={error} />}
        {synthesis?.status === "error" && synthesis.error_message && <ErrorNote text={synthesis.error_message} />}

        {!synthesis && (
          <p className="max-w-prose font-body text-sm leading-relaxed text-brand-gray">
            No briefing was generated for this call, for example after "End without briefing" or a
            dropped connection. Generate Briefing runs the synthesis over the saved transcript and
            insights now.
          </p>
        )}

        {synthesis && (
          <>
            {layout.blocks.map((block) =>
              block.kind === "pair" ? (
                <div key={`${block.sections[0].key}+${block.sections[1].key}`} className={`grid gap-8 ${block.cols}`}>
                  {block.sections.map((section) => (
                    <ItemSection key={section.key} label={section.label} items={section.items} />
                  ))}
                </div>
              ) : (
                <ItemSection
                  key={block.section.key}
                  label={block.section.label}
                  items={block.section.items}
                  lead={block.kind === "lead"}
                />
              ),
            )}

            <ClustersSection clusters={clusters} />
          </>
        )}

        {signalHistoryCount > 0 && (
          <section>
            <SectionHeading label="Strategic signal history" count={signalHistoryCount} />
            <p className="mt-2 max-w-prose font-body text-xs text-brand-mid-gray">
              Durable signals observed across the conversation. They survive a briefing refresh.
            </p>
            <SignalHistory sessionId={session.id} count={signalHistoryCount} />
          </section>
        )}

        {(arbiterNotes || layout.missingNote) && (
          <footer className="space-y-3 border-t border-brand-light-gray-1 pt-6">
            {arbiterNotes && (
              <p className="max-w-prose font-body text-sm italic leading-relaxed text-brand-mid-gray">
                <span className="font-semibold not-italic text-brand-gray">Arbiter notes. </span>
                {arbiterNotes}
              </p>
            )}
            {layout.missingNote && (
              <p className="max-w-prose font-body text-xs text-brand-mid-gray">{layout.missingNote}</p>
            )}
          </footer>
        )}
      </div>
    </article>
  );
}
