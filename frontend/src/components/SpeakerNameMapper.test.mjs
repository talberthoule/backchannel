import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const componentPath = fileURLToPath(new URL("./SpeakerNameMapper.tsx", import.meta.url));
const outputDir = await mkdtemp(join(tmpdir(), "speaker-name-mapper-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import SpeakerNameMapper, * as speakerModule from "./SpeakerNameMapper.tsx";
      import { ConfirmProvider } from "./ConfirmProvider.tsx";
      export const enhancementOutcome = speakerModule.enhancementOutcome;
      export const enhancementProgressLabel = speakerModule.enhancementProgressLabel;
      export const shouldOfferRetry = speakerModule.shouldOfferRetry;
      export function renderMapper(props) {
        // The mapper's confirmations use the themed useConfirm() hook, which
        // requires a ConfirmProvider ancestor.
        return renderToStaticMarkup(
          React.createElement(
            ConfirmProvider,
            null,
            React.createElement(SpeakerNameMapper, props),
          ),
        );
      }
    `,
    resolveDir: dirname(componentPath),
    sourcefile: "speaker-name-mapper-test-entry.tsx",
    loader: "tsx",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: outputPath,
});

const { enhancementOutcome, enhancementProgressLabel, renderMapper, shouldOfferRetry } = createRequire(import.meta.url)(outputPath);

after(async () => {
  await rm(outputDir, { recursive: true, force: true });
});

const session = {
  id: "session-1",
  name: "Meeting",
  state: "completed",
  speaker_context_dirty: true,
  speaker_context_enhanced_at: null,
};
const speaker = {
  id: "speaker-1",
  session_id: "session-1",
  name: "Participant with a fully readable long name",
  role: "",
  color: "#0d9488",
  is_user: false,
  speaker_type: "external",
  display_name: "Alexandra Example",
  display_name_enabled: true,
};
const noop = () => {};

test("speaker rows render long names in a wrapping layout without truncation classes", () => {
  const markup = renderMapper({
    session,
    speakers: [speaker],
    onRefresh: noop,
    onRefreshSession: noop,
    onRefreshQuestions: noop,
    onRefreshSynthesis: async () => {},
  });

  assert.match(markup, /Participant with a fully readable long name/);
  assert.match(markup, /flex-wrap/);
  assert.doesNotMatch(markup, /\bw-36\b/);
  assert.doesNotMatch(markup, /\btruncate\b/);
});

test("partial and error Briefing outcomes stay retryable and never use success copy", () => {
  assert.equal(typeof enhancementOutcome, "function");

  for (const briefingStatus of ["partial", "error"]) {
    const outcome = enhancementOutcome({
      status: "partial",
      applied_operations: 2,
      enhanced_insights: 4,
      speaker_context_dirty: true,
      speaker_context_enhanced_at: null,
      briefing_updated: false,
      briefing_status: briefingStatus,
      error: `Briefing revalidation ${briefingStatus}. Retry Enhance Insights.`,
    });

    assert.equal(outcome.tone, "warning");
    assert.match(outcome.message, /Retry Enhance Insights/);
    assert.doesNotMatch(outcome.message, /Revalidated the Briefing and all Insights/);
  }
});

test("running revalidation reports observable batch progress", () => {
  assert.equal(
    enhancementProgressLabel({
      status: "running",
      completed_batches: 2,
      total_batches: 5,
    }),
    "Revalidating 2/5 batches...",
  );
});

test("finished runs never keep an in-progress banner", () => {
  for (const status of ["completed", "partial", "failed", "unchanged"]) {
    assert.equal(
      enhancementProgressLabel({ status, completed_batches: 0, total_batches: 2 }),
      "",
      `expected no progress label for status ${status}`,
    );
  }
});

test("only finished-with-failures runs offer the failed-batch retry", () => {
  assert.equal(shouldOfferRetry(null), false);
  assert.equal(shouldOfferRetry({ status: "running" }), false);
  assert.equal(shouldOfferRetry({ status: "completed" }), false);
  assert.equal(shouldOfferRetry({ status: "unchanged" }), false);
  assert.equal(shouldOfferRetry({ status: "partial" }), true);
  assert.equal(shouldOfferRetry({ status: "failed" }), true);
});

test("failure outcomes surface the persisted run reason", () => {
  const outcome = enhancementOutcome({
    status: "partial",
    briefing_updated: false,
    briefing_status: "pending",
    speaker_context_dirty: true,
    speaker_context_enhanced_at: null,
    enhanced_insights: 0,
    error: "1 revalidation batch failed. Gemini quota/spending cap exhausted - raise the cap in AI Studio or switch the model in Admin.",
  });

  assert.equal(outcome.tone, "warning");
  assert.match(outcome.message, /Gemini quota\/spending cap exhausted/);
});
