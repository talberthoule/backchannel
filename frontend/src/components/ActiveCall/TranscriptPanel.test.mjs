/**
 * The live transcript's search: hidden behind a quiet magnifier (or Ctrl+F
 * with the panel focused) so the call screen keeps ALP-305's quiet, and the
 * matching itself is plain, literal, and case-insensitive.
 */

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const componentDir = dirname(fileURLToPath(new URL("./TranscriptPanel.tsx", import.meta.url)));
const outputDir = await mkdtemp(join(tmpdir(), "transcript-panel-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import TranscriptPanel from "./TranscriptPanel.tsx";
      import { findTranscriptMatches, highlightParts } from "./transcriptSearch.ts";
      export { findTranscriptMatches, highlightParts };
      export function render(props) {
        return renderToStaticMarkup(React.createElement(TranscriptPanel, props));
      }
    `,
    resolveDir: componentDir,
    sourcefile: "transcript-panel-test-entry.tsx",
    loader: "tsx",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: outputPath,
});

const { render, findTranscriptMatches, highlightParts } = createRequire(import.meta.url)(outputPath);

after(async () => {
  await rm(outputDir, { recursive: true, force: true });
});

const entry = (text, index) => ({
  id: `t-${index}`,
  session_id: "s1",
  text,
  timestamp: "2026-08-31T10:00:00Z",
  speaker_id: null,
});

const transcripts = [
  "We can hold the $1.2M (approx) ceiling.",
  "Maya will send the evidence pack.",
  "Back to the ceiling talk.",
].map(entry);

test("the expanded panel offers search quietly; the input stays hidden until asked for", () => {
  const html = render({ transcripts, speakers: [], collapsed: false });

  assert.match(html, /aria-label="Search live transcript"/);
  assert.match(html, /Search transcript \(Ctrl\+F\)/);
  // Closed by default: no input, no match counter.
  assert.doesNotMatch(html, /placeholder="Search transcript"/);
});

test("the collapsed rail carries no search affordance", () => {
  const html = render({ transcripts, speakers: [], collapsed: true });

  assert.doesNotMatch(html, /aria-label="Search live transcript"/);
});

test("matching is case-insensitive and trims the query", () => {
  assert.deepEqual(findTranscriptMatches(transcripts, "CEILING"), [0, 2]);
  assert.deepEqual(findTranscriptMatches(transcripts, "  ceiling  "), [0, 2]);
  assert.deepEqual(findTranscriptMatches(transcripts, "   "), []);
  assert.deepEqual(findTranscriptMatches(transcripts, "no such phrase"), []);
});

test("regex metacharacters in the query are treated literally", () => {
  assert.deepEqual(findTranscriptMatches(transcripts, "$1.2M (approx)"), [0]);
  // The dot is literal: "1x2M" must not match "$1.2M".
  assert.deepEqual(findTranscriptMatches(transcripts, "1x2M"), []);
});

test("highlighting round-trips the text and marks every occurrence", () => {
  const parts = highlightParts("Ceiling talk about the ceiling", "ceiling");

  assert.equal(parts.map((part) => part.text).join(""), "Ceiling talk about the ceiling");
  assert.deepEqual(
    parts.filter((part) => part.hit).map((part) => part.text),
    ["Ceiling", "ceiling"],
  );
});

for (const count of [0, 18, 40, 41, 1036, 10000]) {
  test(`${count} transcript entries mount only the newest 40 rows`, () => {
    const items = Array.from({ length: count }, (_, i) => entry(`Speech number ${i}`, i));
    const html = render({ transcripts: items, speakers: [] });
    assert.equal((html.match(/data-entry-index=/g) || []).length, Math.min(count, 40));
    assert.equal(html.includes('aria-label="Transcript pages"'), count > 40);
    if (count > 0) assert.ok(html.includes(`Speech number ${count - 1}<`));
    if (count > 40) assert.ok(!html.includes(`Speech number ${count - 41}<`));
  });
}

test("a single explicit interim row is styled live, but a newly saved row is not", () => {
  const recent = { ...entry("Final speech", 0), timestamp: new Date().toISOString() };
  const html = render({ transcripts: [recent, { text: "Live speech", timestamp: recent.timestamp, interim: true }], speakers: [] });
  assert.equal((html.match(/animate-pulse/g) || []).length, 1);
  const single = render({ transcripts: [{ ...recent, interim: true }], speakers: [] });
  assert.ok(single.includes("animate-pulse"));
  const saved = render({ transcripts: [recent, recent], speakers: [] });
  assert.ok(!saved.includes("animate-pulse"));
});

test("memoized transcript rows preserve speaker display names and invalid timestamps", () => {
  const html = render({
    transcripts: [{ ...entry("Attributed speech", 0), speaker_id: "speaker-1", timestamp: "unknown-time" }],
    speakers: [{ id: "speaker-1", name: "Speaker 1", display_name: "Test speaker", display_name_enabled: true, color: "#123456" }],
  });
  assert.ok(html.includes("Test speaker"));
  assert.ok(html.includes("unknown-time"));
  assert.ok(html.includes("background-color:#123456"));
});

test("segment markers remain visible within the bounded tail", () => {
  const html = render({ transcripts: [entry("--- resumed ---", 0)], speakers: [] });
  assert.ok(html.includes("--- resumed ---"));
  assert.equal((html.match(/data-entry-index=/g) || []).length, 1);
});
