import type { Session, SessionSynthesis, SynthesisSectionItem } from "../../types";

interface BriefingViewProps {
  session: Session;
  synthesis: SessionSynthesis | null;
  onRefresh: () => Promise<void>;
  refreshing: boolean;
  error?: string | null;
}

function Section({ title, items }: { title: string; items: SynthesisSectionItem[] }) {
  return (
    <section className="rounded-lg bg-surface p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-display text-sm font-semibold uppercase tracking-wide text-brand-teal">{title}</h3>
        <span className="rounded-full bg-brand-light-gray-2 px-2 py-0.5 font-body text-xs text-brand-mid-gray">
          {items.length}
        </span>
      </div>
      {items.length === 0 ? (
        <p className="font-body text-sm text-brand-mid-gray">No items captured.</p>
      ) : (
        <div className="space-y-3">
          {items.map((item, index) => (
            <div key={`${item.title}-${index}`} className="border-l-2 border-brand-teal-light pl-3">
              <p className="font-body text-sm font-semibold text-brand-dark-gray">
                {item.title || item.summary}
              </p>
              {item.summary && item.title && (
                <p className="mt-1 font-body text-sm leading-relaxed text-brand-gray">{item.summary}</p>
              )}
              {(item.owner || item.status) && (
                <p className="mt-1 font-body text-xs text-brand-mid-gray">
                  {[item.owner, item.status].filter(Boolean).join(" | ")}
                </p>
              )}
              {item.rationale && (
                <p className="mt-1 font-body text-xs leading-relaxed text-brand-mid-gray">{item.rationale}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

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

export default function BriefingView({ session, synthesis, onRefresh, refreshing, error }: BriefingViewProps) {
  const updatedAt = synthesis?.updated_at || synthesis?.created_at || null;
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
      <div className="rounded-lg bg-surface p-5 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-display text-lg font-bold text-brand-dark-gray">Conversation Briefing</h2>
            <p className="mt-1 font-body text-sm text-brand-gray">
              Dual-lens synthesis settled by the briefing arbiter.
            </p>
            {updatedAt && (
              <p className="mt-1 font-body text-xs text-brand-mid-gray">
                Updated {new Date(updatedAt).toLocaleString()} | Status: {synthesis?.status}
              </p>
            )}
          </div>
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="rounded-lg bg-brand-teal px-4 py-2 font-body text-sm font-semibold text-white transition-colors hover:bg-brand-teal-dark disabled:cursor-wait disabled:bg-brand-mid-gray"
          >
            {actionLabel}
          </button>
        </div>
        {error && (
          <div className="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2">
            <p className="font-body text-sm text-red-700">{error}</p>
          </div>
        )}
        {synthesis?.status === "error" && synthesis.error_message && (
          <div className="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2">
            <p className="font-body text-sm text-red-700">{synthesis.error_message}</p>
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

      {synthesis && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Section title="Top 3 Outcomes" items={synthesis.top_outcomes.slice(0, 3)} />
            <Section title={labels.objectives} items={synthesis.client_objectives} />
            <Section title={labels.opportunities} items={synthesis.top_opportunities} />
            <Section title="Risks / Blockers" items={synthesis.risks_blockers} />
            <Section title="Action Plan" items={synthesis.action_plan} />
            <Section title={labels.questions} items={synthesis.unresolved_discovery_questions} />
          </div>

          {synthesis.clusters.length > 0 && (
            <section className="rounded-lg bg-surface p-4 shadow-sm">
              <h3 className="mb-3 font-display text-sm font-semibold uppercase tracking-wide text-brand-teal">
                Insight Clusters
              </h3>
              <div className="grid gap-3 lg:grid-cols-2">
                {synthesis.clusters.map((cluster) => (
                  <div key={cluster.id} className="rounded-md border border-brand-light-gray-1 px-3 py-2">
                    <p className="font-body text-sm font-semibold text-brand-dark-gray">{cluster.title}</p>
                    <p className="mt-1 font-body text-sm text-brand-gray">{cluster.summary}</p>
                    <p className="mt-1 font-body text-xs text-brand-mid-gray">
                      Confidence: {cluster.confidence}
                    </p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {synthesis.arbiter_notes && (
            <section className="rounded-lg border border-brand-amber/30 bg-brand-amber/10 p-4">
              <h3 className="font-display text-sm font-semibold uppercase tracking-wide text-brand-dark-gray">
                Arbiter Notes
              </h3>
              <p className="mt-2 font-body text-sm leading-relaxed text-brand-gray">{synthesis.arbiter_notes}</p>
            </section>
          )}
        </>
      )}
    </div>
  );
}
