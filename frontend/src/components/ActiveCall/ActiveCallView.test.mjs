/**
 * The End Call window must never look like a fault (ALP-171).
 *
 * Ending the call closes the socket before the post-call refreshes finish, and
 * the active view stays mounted through that gap. Acceptance four measured
 * sixteen seconds of "Connection to the backend was lost" and a Resume Audio
 * button after the user had deliberately ended the call.
 *
 * Also holds the call screen's density contract (ALP-305): the top bar carries
 * meters and controls but not setup information the operator typed themselves,
 * diagnostics stay out of the way, and the transcript column can be put away.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const componentPath = fileURLToPath(new URL("./ActiveCallView.tsx", import.meta.url));
const outputDir = await mkdtemp(join(tmpdir(), "active-call-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import ActiveCallView from "./ActiveCallView.tsx";
      export function render(props) {
        return renderToStaticMarkup(React.createElement(ActiveCallView, props));
      }
    `,
    resolveDir: dirname(componentPath),
    sourcefile: "active-call-test-entry.tsx",
    loader: "tsx",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: outputPath,
});

const { render } = createRequire(import.meta.url)(outputPath);

after(async () => {
  await rm(outputDir, { recursive: true, force: true });
});

const LOST_BANNER = "Connection to the backend was lost";
const RESUME = "Resume Audio";

const noop = () => {};

function props(overrides = {}) {
  return {
    session: {
      id: "s1",
      name: "Acceptance",
      state: "active",
      created_at: new Date(0).toISOString(),
      started_at: new Date(0).toISOString(),
      ended_at: null,
      notes: null,
      meeting_type: "general",
      meeting_context: "",
      group_id: null,
      speaker_context_dirty: false,
      speaker_context_enhanced_at: null,
    },
    questions: [],
    transcripts: [],
    directives: [],
    speakers: [],
    interimText: "",
    // The socket is already gone: this is the state the window is measured in.
    status: "disconnected",
    isCapturing: false,
    isStarting: false,
    audioLevel: 0,
    audioStats: { chunksSent: 0, bytesSent: 0, chunksDropped: 0, lastSentAt: null },
    synthesis: null,
    activity: null,
    postProcessing: null,
    onEndCall: noop,
    onResumeAudio: noop,
    onAddDirective: noop,
    onAsk: noop,
    askModels: [],
    askModelId: "",
    onAskModelChange: noop,
    localOnly: false,
    pendingAsk: null,
    askError: null,
    onStarQuestion: noop,
    onDismissQuestion: noop,
    onVoteQuestion: noop,
    ...overrides,
  };
}

test("ending the call never shows the lost-connection banner or Resume", () => {
  // Exactly the acceptance-four window: stop resolved completed, socket closed,
  // capture stopped, and the post-call refreshes still in flight.
  const html = render(props({ ending: true }));

  assert.doesNotMatch(html, new RegExp(LOST_BANNER));
  assert.doesNotMatch(html, new RegExp(RESUME));
  assert.doesNotMatch(html, /not recording/);
  // It says what is actually happening instead.
  assert.match(html, /Wrapping up this call/);
});

test("a genuine mid-call socket loss still shows both, untouched", () => {
  // ALP-165 depends on this banner; the fix must not weaken it.
  const html = render(props({ ending: false }));

  assert.match(html, new RegExp(LOST_BANNER));
  assert.match(html, new RegExp(RESUME));
  assert.match(html, /not recording/);
  assert.doesNotMatch(html, /Wrapping up this call/);
});

test("a connected call in progress shows neither the banner nor wrapping-up", () => {
  const html = render(props({ status: "connected", isCapturing: true }));

  assert.doesNotMatch(html, new RegExp(LOST_BANNER));
  assert.doesNotMatch(html, /Wrapping up this call/);
});

test("the pending ask renders above the insight list", () => {
  const src = readFileSync(new URL("./ActiveCallView.tsx", import.meta.url), "utf8");
  assert.match(src, /pendingAsk/);
  assert.ok(
    src.indexOf("pendingAsk") < src.indexOf("<QuestionList"),
    "the pending card must render before the list",
  );
});

test("the bar receives the ask handler and model props", () => {
  const src = readFileSync(new URL("./ActiveCallView.tsx", import.meta.url), "utf8");
  assert.match(src, /onAsk=\{/);
  assert.match(src, /modelId=\{/);
  assert.match(src, /localOnly=\{/);
});

test("the top bar drops the meeting information the operator already entered", () => {
  const html = render(
    props({
      status: "connected",
      isCapturing: true,
      session: {
        ...props().session,
        meeting_type: "client_sales",
        meeting_context: "Renewal call with the platform team",
      },
    }),
  );

  assert.doesNotMatch(html, /Client \/ prospect/);
  assert.doesNotMatch(html, /Conversation type/);
  assert.doesNotMatch(html, /Renewal call with the platform team/);
  // What belongs there stays: the meters, the timer and End Call.
  assert.match(html, /Microphone input level/);
  assert.match(html, /End Call/);
});

test("a healthy call says it is listening exactly once", () => {
  const html = render(
    props({ status: "connected", isCapturing: true, systemAudioActive: true }),
  );

  // Two meters and a status word used to give the bar three copies of it.
  assert.equal(html.match(/Listening/g)?.length, 1);
  // Both meters are still there and still distinguishable.
  assert.match(html, /Microphone input level/);
  assert.match(html, /Meeting audio input level/);
});

test("a call that is not simply listening still says what it is doing", () => {
  assert.match(render(props({ isStarting: true })), /Starting audio\.\.\./);
  assert.match(render(props({ status: "connecting" })), /connecting/);
});

test("diagnostics are an unlabeled icon whose readout stays closed", () => {
  const html = render(props({ status: "connected", isCapturing: true }));

  assert.match(html, /aria-label="Audio diagnostics"/);
  // No wide "Debug" pill in the flow of the bar, and no readout until asked.
  assert.doesNotMatch(html, />Debug</);
  assert.doesNotMatch(html, /audio sent:/);
});

test("the transcript column can be put away", () => {
  const html = render(props({ status: "connected", isCapturing: true }));

  assert.match(html, /Live Transcription/);
  assert.match(html, /Hide live transcription/);
});

test("captured strategic signals reach the insight list as a Strategic filter", () => {
  const signal = (title, seen) => ({
    section: "strategic_signals",
    title,
    summary: `${title} detail`,
    rationale: "",
    first_seen: seen,
    last_seen: seen,
    count: 1,
  });

  const html = render(
    props({
      status: "connected",
      isCapturing: true,
      synthesis: {
        mode: "live",
        status: "completed",
        strategic_signals: [],
        top_outcomes: [],
        top_opportunities: [],
        risks_blockers: [],
        action_plan: [],
        unresolved_discovery_questions: [],
        clusters: [],
        signal_history: [
          signal("Budget owner changed", "2026-08-16T10:00:00Z"),
          signal("Security review is the gate", "2026-08-16T10:05:00Z"),
        ],
        signal_history_count: 2,
        created_at: "2026-08-16T10:05:00Z",
        updated_at: "2026-08-16T10:05:00Z",
      },
    }),
  );

  // The chip is present and counts every captured signal, not just the panelled ones.
  assert.match(html, /Strategic/);
  assert.match(html, /aria-pressed="false"[^>]*>Strategic/);
  // Closed by default: All is still the selected filter.
  assert.doesNotMatch(html, /Budget owner changed/);
});

test("the Strategic chip stays hidden when no signal has been captured", () => {
  const html = render(props({ status: "connected", isCapturing: true }));

  assert.doesNotMatch(html, />Strategic</);
});
