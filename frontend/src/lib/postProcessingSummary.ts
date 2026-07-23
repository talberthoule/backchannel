// Formats the post-processing summary line shown under the "Post-processing"
// progress panel and the post-call completion banner.
//
// The backend's drain `details` counters describe ONLY the final analysis
// pass that runs while the call is ending:
// - insights_saved: new insights created by the final consolidated analyst pass
// - synthesizer_ops: updates applied to already-saved insights by the final
//   synthesizer reconciliation pass
// - opportunity_ops: offering matches applied by the final opportunity pass
// - session_insight_total: the session's total insight count at drain
//   completion (server-counted; may be absent on older backends)
//
// The copy must make the pass-vs-lifetime distinction explicit so "3 new"
// next to a session header showing 23 total insights is not confusing.

function count(details: Record<string, unknown>, key: string): number {
  const value = Number(details[key] ?? 0);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

export function formatPostProcessingSummary(details?: Record<string, unknown>): string | null {
  if (!details) return null;
  const newInsights = count(details, "insights_saved");
  const updates = count(details, "synthesizer_ops");
  const matches = count(details, "opportunity_ops");
  const rawTotal = details.session_insight_total;
  const total =
    typeof rawTotal === "number" && Number.isFinite(rawTotal) && rawTotal >= 0
      ? Math.floor(rawTotal)
      : null;

  const parts = [
    newInsights ? `${newInsights} new insight${newInsights === 1 ? "" : "s"}` : null,
    updates ? `${updates} insight${updates === 1 ? "" : "s"} updated` : null,
    matches ? `${matches} offering match${matches === 1 ? "" : "es"}` : null,
  ].filter(Boolean);

  if (parts.length === 0 && total === null) return null;

  const passText =
    parts.length > 0
      ? `Final analysis pass: ${parts.join(", ")}`
      : "Final analysis pass: no changes";
  if (total === null) return passText;
  return `${passText} - ${total} insight${total === 1 ? "" : "s"} total for this session`;
}
