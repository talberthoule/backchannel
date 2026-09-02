import { useMemo } from "react";
import type { ModelPricingResponse, TokenUsageSummary } from "../../types";
import { estimateCostUsd, estimateSessionCostUsd, formatAudioDuration, formatEstimatedCost } from "../../lib/modelPricing";

interface TokenUsagePanelProps {
  tokenUsage: TokenUsageSummary | null;
  loading: boolean;
  error: boolean;
  pricing: ModelPricingResponse | null;
  onRefresh: () => void;
}

// The post-call Tokens tab: recorded usage and its estimated cost. The fetch
// lives in PostCallView because the Overview's cost tile shares it; this
// panel only renders what it is handed.
export default function TokenUsagePanel({ tokenUsage, loading, error, pricing, onRefresh }: TokenUsagePanelProps) {
  return (
    <div className="rounded-xl bg-surface p-6 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-lg font-semibold text-brand-dark-gray">Token usage</h2>
          <p className="mt-1 text-sm text-brand-mid-gray">LLM activity recorded for this session.</p>
        </div>
        {!loading && (
          <button
            type="button"
            onClick={onRefresh}
            className="rounded-md border border-brand-light-gray-1 px-3 py-1.5 text-sm font-medium text-brand-teal hover:bg-brand-light-gray-2"
          >
            Refresh
          </button>
        )}
      </div>

      {loading ? (
        <p className="mt-6 text-sm text-brand-mid-gray" role="status">Loading token usage...</p>
      ) : error ? (
        <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4" role="alert">
          <p className="text-sm text-red-700">Token usage could not be loaded.</p>
        </div>
      ) : tokenUsage ? (
        <div className="mt-6 space-y-6">
          <div className="rounded-lg border border-brand-teal/20 bg-brand-teal/5 p-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-brand-gray">Estimated cost</p>
            <p className="mt-1 font-display text-3xl font-semibold tabular-nums text-brand-dark-gray">
              {formatEstimatedCost(
                pricing ? estimateSessionCostUsd(tokenUsage.by_model, pricing.models) : null,
              )}
            </p>
            <p className="mt-2 text-sm text-brand-mid-gray">
              {tokenUsage.total_tokens.toLocaleString()} tokens
              {" ("}
              {tokenUsage.input_tokens.toLocaleString()} input / {tokenUsage.output_tokens.toLocaleString()} output
              {tokenUsage.thinking_tokens > 0 && (
                <> / {tokenUsage.thinking_tokens.toLocaleString()} thinking</>
              )}
              {")"}
              {tokenUsage.audio_seconds > 0 && (
                <> plus {formatAudioDuration(tokenUsage.audio_seconds)} of audio</>
              )}
            </p>
            {tokenUsage.thinking_tokens > 0 && (
              <p className="mt-1 text-xs text-brand-mid-gray">
                Thinking tokens are billed at output rates.
              </p>
            )}
            {((tokenUsage.audio_input_tokens ?? 0) > 0 || (tokenUsage.audio_output_tokens ?? 0) > 0) && (
              <p className="mt-1 text-xs text-brand-mid-gray">
                {(tokenUsage.audio_input_tokens ?? 0).toLocaleString()} of the input tokens
                {(tokenUsage.audio_output_tokens ?? 0) > 0 && (
                  <> and {(tokenUsage.audio_output_tokens ?? 0).toLocaleString()} of the output tokens</>
                )}
                {" "}were audio, priced at the audio rate where the provider publishes one.
              </p>
            )}
            {(tokenUsage.cached_input_tokens ?? 0) > 0 && (
              <p className="mt-1 text-xs text-brand-mid-gray">
                {(tokenUsage.cached_input_tokens ?? 0).toLocaleString()} of the input tokens were served from the provider's prompt cache, priced at the cached rate.
              </p>
            )}
            {tokenUsage.audio_seconds > 0 && (
              <p className="mt-1 text-xs text-brand-mid-gray">
                The live gateway is billed per minute of audio, not per token.
              </p>
            )}
          </div>

          {tokenUsage.total_tokens === 0 && tokenUsage.audio_seconds === 0 ? (
            <p className="text-sm text-brand-mid-gray">No usage was recorded for this session.</p>
          ) : (
            <>
              <TokenBreakdownTable title="By source" rows={tokenUsage.by_source} showSource pricing={pricing} showRateNote={false} />
              <TokenBreakdownTable title="By model" rows={tokenUsage.by_model} pricing={pricing} />
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

function TokenBreakdownTable({
  title,
  rows,
  showSource = false,
  pricing = null,
  showRateNote = true,
}: {
  title: string;
  rows: TokenUsageSummary["by_source"];
  showSource?: boolean;
  // When set, adds an Est. cost column plus a session total row.
  pricing?: ModelPricingResponse | null;
  // Both tables price their rows, but the rate caveat only needs saying once.
  showRateNote?: boolean;
}) {
  const sessionCost = pricing ? estimateSessionCostUsd(rows, pricing.models) : null;
  // The API orders by tokens, which ranks a duration-billed row (zero tokens,
  // real money) last. Cost is the only axis the two billing units share, and
  // it is only known here, so the re-sort happens at render.
  const ordered = useMemo(() => {
    if (!pricing) return rows;
    const cost = (row: TokenUsageSummary["by_source"][number]) =>
      estimateCostUsd(pricing.models[row.model_id], row) ?? -1;
    return [...rows].sort((a, b) => cost(b) - cost(a));
  }, [rows, pricing]);
  // Only surface the thinking column when something actually thought, so
  // non-reasoning sessions keep the narrower table. Same for audio duration,
  // which is non-zero only when a duration-billed model ran, and for the
  // cached and audio token slices, which most text-only sessions never see.
  const showThinking = rows.some((row) => row.thinking_tokens > 0);
  const showAudio = rows.some((row) => (row.audio_seconds ?? 0) > 0);
  const showCached = rows.some((row) => (row.cached_input_tokens ?? 0) > 0);
  const showAudioTokens = rows.some((row) => (row.audio_input_tokens ?? 0) > 0 || (row.audio_output_tokens ?? 0) > 0);
  const audioTokensCell = (row: TokenUsageSummary["by_source"][number]) => {
    const input = row.audio_input_tokens ?? 0;
    const output = row.audio_output_tokens ?? 0;
    if (input === 0 && output === 0) return "-";
    return output > 0 ? `${input.toLocaleString()} in / ${output.toLocaleString()} out` : input.toLocaleString();
  };
  return (
    <section>
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-brand-gray">{title}</h3>
      <div className="overflow-x-auto rounded-lg border border-brand-light-gray-1">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-brand-light-gray-2 text-xs uppercase tracking-wide text-brand-gray">
            <tr>
              {showSource && <th scope="col" className="px-4 py-3 font-semibold">Source</th>}
              <th scope="col" className="px-4 py-3 font-semibold">Model</th>
              <th scope="col" className="px-4 py-3 text-right font-semibold">Input</th>
              <th scope="col" className="px-4 py-3 text-right font-semibold">Output</th>
              {showThinking && <th scope="col" className="px-4 py-3 text-right font-semibold">Thinking</th>}
              {showCached && <th scope="col" className="px-4 py-3 text-right font-semibold" title="Input tokens served from the provider's prompt cache">Cached in</th>}
              {showAudioTokens && <th scope="col" className="px-4 py-3 text-right font-semibold" title="Tokens the provider counted as audio">Audio tokens</th>}
              {showAudio && <th scope="col" className="px-4 py-3 text-right font-semibold">Audio</th>}
              <th scope="col" className="px-4 py-3 text-right font-semibold">Total</th>
              {pricing && <th scope="col" className="px-4 py-3 text-right font-semibold">Est. cost</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-brand-light-gray-1">
            {ordered.map((row) => (
              <tr key={`${row.source ?? "model"}-${row.model_id}`}>
                {showSource && <th scope="row" className="px-4 py-3 font-medium text-brand-dark-gray">{row.source}</th>}
                <td className="px-4 py-3 font-mono text-xs text-brand-gray">{row.model_id}</td>
                <td className="px-4 py-3 text-right tabular-nums text-brand-gray">{row.input_tokens.toLocaleString()}</td>
                <td className="px-4 py-3 text-right tabular-nums text-brand-gray">{row.output_tokens.toLocaleString()}</td>
                {showThinking && (
                  <td className="px-4 py-3 text-right tabular-nums text-brand-gray">{row.thinking_tokens.toLocaleString()}</td>
                )}
                {showCached && (
                  <td className="px-4 py-3 text-right tabular-nums text-brand-gray">{(row.cached_input_tokens ?? 0) > 0 ? (row.cached_input_tokens ?? 0).toLocaleString() : "-"}</td>
                )}
                {showAudioTokens && (
                  <td className="px-4 py-3 text-right tabular-nums text-brand-gray">{audioTokensCell(row)}</td>
                )}
                {showAudio && (
                  <td className="px-4 py-3 text-right tabular-nums text-brand-gray">{formatAudioDuration(row.audio_seconds ?? 0)}</td>
                )}
                <td className="px-4 py-3 text-right font-semibold tabular-nums text-brand-dark-gray">{row.total_tokens.toLocaleString()}</td>
                {pricing && (
                  <td className="px-4 py-3 text-right tabular-nums text-brand-gray">
                    {formatEstimatedCost(estimateCostUsd(pricing.models[row.model_id], row))}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
          {pricing && (
            <tfoot className="border-t border-brand-light-gray-1 bg-brand-light-gray-2/60">
              <tr>
                <th scope="row" colSpan={(showSource ? 5 : 4) + (showThinking ? 1 : 0) + (showCached ? 1 : 0) + (showAudioTokens ? 1 : 0) + (showAudio ? 1 : 0)} className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide text-brand-gray">
                  Session estimate
                </th>
                <td className="px-4 py-3 text-right font-semibold tabular-nums text-brand-dark-gray">
                  {formatEstimatedCost(sessionCost)}
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      {pricing && showRateNote && (
        <p className="mt-2 text-xs text-brand-mid-gray">
          Est. cost uses each provider's standard paid-tier rates as of {pricing.as_of}: cached and audio tokens at their published cached and audio rates where the provider lists one (otherwise the plain text rate), thinking at the output rate, and the per-minute rate for models billed by audio duration. No long-context surcharges or cache-storage fees. Models without published pricing show - and are excluded from the total.
        </p>
      )}
    </section>
  );
}
