import { useState, type ComponentType } from "react";
import {
  Activity,
  AlertTriangle,
  CheckSquare,
  ChevronDown,
  HelpCircle,
  Layers,
  ListChecks,
  RefreshCw,
  StickyNote,
  Target,
  TrendingUp,
  Trophy,
} from "lucide-react";
import type { InsightCluster, Session, SessionSynthesis, SynthesisSectionItem } from "../../types";
import SignalHistory from "../SignalHistory";

interface BriefingViewProps {
  session: Session;
  synthesis: SessionSynthesis | null;
  signalHistoryCount: number;
  onRefresh: () => Promise<void>;
  refreshing: boolean;
  error?: string | null;
}

type Icon = ComponentType<{ className?: string }>;

function sectionLabels(session: Session) {
  switch (session.meeting_type) {
    case "internal_enablement":
      return {
        objectives: "Learning Objectives",
        opportunities: "Enablement Opportunities",
        questions: "Open Learning Questions",
      };
    case "internal_checkin":
      return {
        objectives: "Objectives / Needs",
        opportunities: "Support Opportunities",
        questions: "Open Questions",
      };
    case "vendor_partner":
      return {
        objectives: "Vendor / Program Objectives",
        opportunities: "Partner Opportunities",
        questions: "Open Vendor / Program Questions",
      };
    case "customer_delivery":
      return {
        objectives: "Project Objectives",
        opportunities: "Delivery Opportunities",
        questions: "Open Delivery Questions",
      };
    case "client_sales":
      return {
        objectives: "Client Objectives",
        opportunities: "Top Opportunities",
        questions: "Unresolved Discovery Questions",
      };
    default:
      return {
        objectives: "Objectives",
        opportunities: "Top Opportunities",
        questions: "Open Questions",
      };
  }
}

// Semantic identity per section: icon + accent color, shared by the header
// chip and every item row so the page reads by color/shape, not just text.
type ToneKey = "objectives" | "opportunities" | "risks" | "action" | "questions" | "signals";

interface ToneStyle {
  headerIcon: Icon;
  itemIcon: Icon;
  border: string;
  chip: string;
  itemBorder: string;
  iconColor: string;
}

const TONE: Record<ToneKey, ToneStyle> = {
  objectives: {
    headerIcon: Target,
    itemIcon: Target,
    border: "border-sky-200 dark:border-sky-900/50",
    chip: "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-400",
    itemBorder: "border-sky-300 dark:border-sky-800",
    iconColor: "text-sky-500 dark:text-sky-400",
  },
  opportunities: {
    headerIcon: TrendingUp,
    itemIcon: TrendingUp,
    border: "border-emerald-200 dark:border-emerald-900/50",
    chip: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
    itemBorder: "border-emerald-300 dark:border-emerald-800",
    iconColor: "text-emerald-500 dark:text-emerald-400",
  },
  risks: {
    headerIcon: AlertTriangle,
    itemIcon: AlertTriangle,
    border: "border-red-200 dark:border-red-900/50",
    chip: "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400",
    itemBorder: "border-red-300 dark:border-red-800",
    iconColor: "text-red-500 dark:text-red-400",
  },
  action: {
    headerIcon: ListChecks,
    itemIcon: CheckSquare,
    border: "border-indigo-200 dark:border-indigo-900/50",
    chip: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-400",
    itemBorder: "border-indigo-300 dark:border-indigo-800",
    iconColor: "text-indigo-500 dark:text-indigo-400",
  },
  questions: {
    headerIcon: HelpCircle,
    itemIcon: HelpCircle,
    border: "border-violet-200 dark:border-violet-900/50",
    chip: "bg-violet-100 text-violet-700 dark:bg-violet-950/40 dark:text-violet-400",
    itemBorder: "border-violet-300 dark:border-violet-800",
    iconColor: "text-violet-500 dark:text-violet-400",
  },
  signals: {
    headerIcon: Activity,
    itemIcon: Activity,
    border: "border-amber-200 dark:border-amber-900/50",
    chip: "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
    itemBorder: "border-amber-300 dark:border-amber-800",
    iconColor: "text-amber-500 dark:text-amber-400",
  },
};

function statusChipTone(status: string): string {
  const s = status.toLowerCase();
  if (/(done|complete|resolved|closed|won|answered)/.test(s)) {
    return "bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-400";
  }
  if (/(block|risk|stall|stuck|lost|urgent|escalat)/.test(s)) {
    return "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400";
  }
  if (/(progress|active|pending|review)/.test(s)) {
    return "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-400";
  }
  return "bg-brand-light-gray-2 text-brand-gray";
}

function synthesisStatusTone(status: string): string {
  switch (status) {
    case "completed":
      return "bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-400";
    case "partial":
      return "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400";
    case "error":
      return "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400";
    default:
      return "bg-brand-light-gray-2 text-brand-gray";
  }
}

function StatusChip({ status }: { status: string }) {
  return (
    <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 font-body text-xs font-medium ${statusChipTone(status)}`}>
      {status}
    </span>
  );
}

function OwnerChip({ owner }: { owner: string }) {
  const initial = owner.trim().charAt(0).toUpperCase() || "?";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-light-gray-2 px-2 py-0.5 font-body text-xs font-medium text-brand-dark-gray">
      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-brand-teal text-[10px] font-bold text-white">
        {initial}
      </span>
      {owner}
    </span>
  );
}

// Progressive disclosure for the "why this matters" rationale text: collapsed
// by default so the default view stays dense with signal, not prose.
function RationaleToggle({ text }: { text?: string }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <div className="mt-1.5">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 font-body text-xs font-medium text-brand-mid-gray transition-colors hover:text-brand-teal"
      >
        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
        Why this matters
      </button>
      {open && (
        <p className="mt-1 font-body text-xs italic leading-relaxed text-brand-mid-gray">{text}</p>
      )}
    </div>
  );
}

function SectionHeading({ icon: IconCmp, label, chipClass, count }: { icon: Icon; label: string; chipClass: string; count: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${chipClass}`}>
        <IconCmp className="h-4 w-4" />
      </span>
      <h3 className="font-display text-sm font-bold text-brand-dark-gray">{label}</h3>
      {count > 0 && (
        <span className={`ml-auto shrink-0 rounded-full px-2 py-0.5 font-body text-xs font-semibold tabular-nums ${chipClass}`}>
          {count}
        </span>
      )}
    </div>
  );
}

// A single briefing section: colored identity header, item rows with
// status and a rationale disclosure, or a compact muted line
// when nothing was captured (never a full empty card).
function InsightSection({
  tone,
  label,
  items,
  className = "",
}: {
  tone: ToneKey;
  label: string;
  items: SynthesisSectionItem[];
  className?: string;
}) {
  const style = TONE[tone];

  if (items.length === 0) {
    return (
      <section className={`rounded-xl border border-dashed border-brand-light-gray-1 p-4 ${className}`}>
        <SectionHeading icon={style.headerIcon} label={label} chipClass={style.chip} count={0} />
        <p className="mt-2 font-body text-xs italic text-brand-mid-gray">Not captured in this briefing.</p>
      </section>
    );
  }

  const ItemIcon = style.itemIcon;
  return (
    <section className={`rounded-xl border ${style.border} bg-surface p-4 shadow-sm ${className}`}>
      <SectionHeading icon={style.headerIcon} label={label} chipClass={style.chip} count={items.length} />
      <ul className="mt-3 space-y-3">
        {items.map((item, index) => (
          <li key={`${item.title}-${index}`} className={`border-l-2 pl-3 ${style.itemBorder}`}>
            <div className="flex items-start gap-2">
              <ItemIcon className={`mt-0.5 h-4 w-4 shrink-0 ${style.iconColor}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-start gap-2">
                  <p className="min-w-0 flex-1 font-body text-sm font-semibold text-brand-dark-gray">
                    {item.title || item.summary}
                  </p>
                  {item.status && <StatusChip status={item.status} />}
                  {item.owner && <OwnerChip owner={item.owner} />}
                </div>
                {item.summary && item.title && (
                  <p className="mt-0.5 font-body text-sm leading-relaxed text-brand-gray">{item.summary}</p>
                )}
                <RationaleToggle text={item.rationale} />
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

// The hero: strongest typography on the page, full width, large numbered
// treatment. This is what a first-time viewer should absorb first.
function OutcomesHero({ items }: { items: SynthesisSectionItem[] }) {
  return (
    <section className="rounded-2xl border border-brand-teal/20 bg-gradient-to-br from-brand-teal/[0.06] to-transparent p-6 shadow-sm">
      <div className="mb-1 flex items-center gap-2">
        <Trophy className="h-5 w-5 text-brand-teal" />
        <h3 className="font-display text-xs font-bold uppercase tracking-wide text-brand-teal">Top 3 Outcomes</h3>
      </div>
      {items.length === 0 ? (
        <p className="mt-3 font-body text-sm italic text-brand-mid-gray">No outcomes captured yet.</p>
      ) : (
        <ol className="mt-2 divide-y divide-brand-teal/10">
          {items.slice(0, 3).map((item, index) => (
            <li key={`${item.title}-${index}`} className="flex gap-4 py-4 first:pt-3 last:pb-1">
              <span className="w-10 shrink-0 font-display text-4xl font-black leading-none tabular-nums text-brand-teal/25 md:text-5xl">
                {index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-start gap-2">
                  <p className="min-w-0 flex-1 font-display text-lg font-bold leading-snug text-brand-dark-gray">
                    {item.title || item.summary}
                  </p>
                  {item.status && <StatusChip status={item.status} />}
                  {item.owner && <OwnerChip owner={item.owner} />}
                </div>
                {item.summary && item.title && (
                  <p className="mt-1 font-body text-sm leading-relaxed text-brand-gray">{item.summary}</p>
                )}
                <RationaleToggle text={item.rationale} />
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function SignalStrip({ items }: { items: SynthesisSectionItem[] }) {
  const style = TONE.signals;
  return (
    <section className={`rounded-xl border ${style.border} bg-surface p-4 shadow-sm`}>
      <SectionHeading icon={style.headerIcon} label="Strategic Signals" chipClass={style.chip} count={items.length} />
      <div className="mt-3 flex flex-wrap gap-3">
        {items.map((item, index) => (
          <div
            key={`${item.title}-${index}`}
            className={`w-full max-w-sm rounded-lg border ${style.itemBorder} bg-brand-light-gray-2/40 p-3 sm:w-auto sm:flex-1`}
          >
            <div className="flex items-start gap-2">
              <Activity className={`mt-0.5 h-4 w-4 shrink-0 ${style.iconColor}`} />
              <div className="min-w-0 flex-1">
                <p className="font-body text-sm font-semibold text-brand-dark-gray">{item.title || item.summary}</p>
                {item.summary && item.title && (
                  <p className="mt-0.5 font-body text-xs leading-relaxed text-brand-gray">{item.summary}</p>
                )}
                <RationaleToggle text={item.rationale} />
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ClusterRow({ clusters }: { clusters: InsightCluster[] }) {
  return (
    <section className="rounded-xl bg-surface p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <Layers className="h-4 w-4 text-brand-mid-gray" />
        <h3 className="font-display text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">
          Insight Clusters
        </h3>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {clusters.map((cluster) => (
          <div
            key={cluster.id}
            className="w-full max-w-xs rounded-lg border border-brand-light-gray-1 px-3 py-2 sm:w-auto sm:flex-1"
          >
            <div className="flex items-center justify-between gap-2">
              <p className="font-body text-sm font-semibold text-brand-dark-gray">{cluster.title}</p>
              <span className="shrink-0 rounded-full bg-brand-light-gray-2 px-1.5 py-0.5 font-body text-[10px] font-medium uppercase tracking-wide text-brand-mid-gray">
                {cluster.confidence}
              </span>
            </div>
            <p className="mt-1 font-body text-xs leading-relaxed text-brand-gray">{cluster.summary}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function ArbiterFootnote({ text }: { text: string }) {
  return (
    <p className="flex items-start gap-2 rounded-lg border border-brand-light-gray-1 bg-brand-light-gray-2/40 px-4 py-3 font-body text-xs italic leading-relaxed text-brand-mid-gray">
      <StickyNote className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span><span className="font-semibold not-italic text-brand-gray">Arbiter notes:</span> {text}</span>
    </p>
  );
}

// Executive at-a-glance strip: five-second read of what happened, plus the
// status/refresh controls. Replaces the old plain header card.
function ExecutiveStrip({
  synthesis,
  onRefresh,
  refreshing,
  error,
  actionLabel,
}: {
  synthesis: SessionSynthesis | null;
  onRefresh: () => Promise<void>;
  refreshing: boolean;
  error?: string | null;
  actionLabel: string;
}) {
  const updatedAt = synthesis?.updated_at || synthesis?.created_at || null;
  // Outcomes chip matches the hero's teal identity rather than a TONE entry.
  const outcomesChip = "bg-brand-teal/10 text-brand-teal";
  const allStats: { key: string; label: string; count: number; icon: Icon; chip: string }[] = synthesis
    ? [
        { key: "outcomes", label: "Outcomes", count: synthesis.top_outcomes.length, icon: Trophy, chip: outcomesChip },
        { key: "actions", label: "Actions", count: synthesis.action_plan.length, icon: ListChecks, chip: TONE.action.chip },
        { key: "risks", label: "Risks", count: synthesis.risks_blockers.length, icon: AlertTriangle, chip: TONE.risks.chip },
        { key: "questions", label: "Open Qs", count: synthesis.unresolved_discovery_questions.length, icon: HelpCircle, chip: TONE.questions.chip },
      ]
    : [];
  const stats = allStats.filter((s) => s.count > 0);

  return (
    <div className="rounded-xl bg-surface p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-lg font-bold text-brand-dark-gray">Conversation Briefing</h2>
          <p className="mt-1 font-body text-sm text-brand-gray">
            Dual-lens synthesis settled by the briefing arbiter.
          </p>
        </div>
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-brand-teal px-4 py-2 font-body text-sm font-semibold text-white transition-colors hover:bg-brand-teal-dark disabled:cursor-wait disabled:bg-brand-mid-gray"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          {actionLabel}
        </button>
      </div>

      {synthesis && (stats.length > 0 || updatedAt) && (
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-brand-light-gray-1 pt-4">
          {stats.map((s) => (
            <span
              key={s.key}
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-body text-xs font-semibold ${s.chip}`}
            >
              <s.icon className="h-3.5 w-3.5" />
              <span className="tabular-nums">{s.count}</span>
              {s.label}
            </span>
          ))}
          <span className={`inline-flex items-center rounded-full px-2.5 py-1 font-body text-xs font-semibold capitalize ${synthesisStatusTone(synthesis.status)}`}>
            {synthesis.status}
          </span>
          {updatedAt && (
            <span className="font-body text-xs text-brand-mid-gray">
              Updated {new Date(updatedAt).toLocaleString()}
            </span>
          )}
        </div>
      )}

      {error && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 dark:border-red-900/50 dark:bg-red-950/30">
          <p className="font-body text-sm text-red-700 dark:text-red-400">{error}</p>
        </div>
      )}
      {synthesis?.status === "error" && synthesis.error_message && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 dark:border-red-900/50 dark:bg-red-950/30">
          <p className="font-body text-sm text-red-700 dark:text-red-400">{synthesis.error_message}</p>
        </div>
      )}
      {!synthesis && (
        <p className="mt-4 font-body text-sm text-brand-mid-gray">
          No briefing was generated for this call (for example after "End without briefing" or a
          dropped connection). Use Generate Briefing to run the briefing synthesis over the saved
          transcript and insights now.
        </p>
      )}
    </div>
  );
}

export default function BriefingView({ session, synthesis, signalHistoryCount, onRefresh, refreshing, error }: BriefingViewProps) {
  const labels = sectionLabels(session);
  const actionLabel = refreshing
    ? synthesis
      ? "Refreshing..."
      : "Generating..."
    : synthesis
      ? "Refresh Briefing"
      : "Generate Briefing";

  return (
    <div className="space-y-4">
      <ExecutiveStrip
        synthesis={synthesis}
        onRefresh={onRefresh}
        refreshing={refreshing}
        error={error}
        actionLabel={actionLabel}
      />

      <SignalHistory
        sessionId={session.id}
        count={signalHistoryCount}
        heading="Strategic Signal History"
      />

      {synthesis && (
        <>
          <OutcomesHero items={synthesis.top_outcomes} />

          <div className="grid gap-4 lg:grid-cols-12">
            <InsightSection tone="risks" label="Risks / Blockers" items={synthesis.risks_blockers} className="lg:col-span-5" />
            <InsightSection tone="action" label="Action Plan" items={synthesis.action_plan} className="lg:col-span-7" />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <InsightSection tone="objectives" label={labels.objectives} items={synthesis.client_objectives} />
            <InsightSection tone="opportunities" label={labels.opportunities} items={synthesis.top_opportunities} />
            <InsightSection tone="questions" label={labels.questions} items={synthesis.unresolved_discovery_questions} />
          </div>

          {synthesis.strategic_signals.length > 0 && <SignalStrip items={synthesis.strategic_signals} />}

          {synthesis.clusters.length > 0 && <ClusterRow clusters={synthesis.clusters} />}

          {synthesis.arbiter_notes && <ArbiterFootnote text={synthesis.arbiter_notes} />}
        </>
      )}
    </div>
  );
}
