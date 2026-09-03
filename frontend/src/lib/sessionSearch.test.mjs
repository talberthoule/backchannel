import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const modulePath = fileURLToPath(new URL("./sessionSearch.ts", import.meta.url));
const outputDir = await mkdtemp(join(tmpdir(), "session-search-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  stdin: {
    contents: `export { filterSessions, dateSearchTerms, normalizeQuery } from "./sessionSearch.ts";`,
    resolveDir: dirname(modulePath),
    sourcefile: "session-search-entry.ts",
    loader: "ts",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: outputPath,
  logLevel: "silent",
});

const { filterSessions } = createRequire(import.meta.url)(outputPath);
after(() => rm(outputDir, { recursive: true, force: true }));

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

// Local noon keeps the calendar date the same whatever zone the test runs in.
function at(year, month, day) {
  return new Date(year, month - 1, day, 12).toISOString();
}

const sessions = [
  { id: "a", name: "Recovery readiness review", group_id: null, state: "completed",
    created_at: at(2026, 10, 8), started_at: at(2026, 10, 8) },
  { id: "b", name: "Pipeline review", group_id: null, state: "completed",
    created_at: at(2026, 11, 2), started_at: at(2026, 11, 2) },
];

// The post-call chat has no group list to search, so it passes an empty one.
// Date matching has to survive that, which is the whole point of the fix.
test("date search works with no groups, the way the chat scope picker calls it", () => {
  for (const query of ["october", "oct 8", "8", "08", "10/8", "10-08", "2026-10-08"]) {
    const found = filterSessions(sessions, [], query);
    assert.ok(
      found.some((session) => session.id === "a"),
      `"${query}" did not find the 8 October session`,
    );
  }
  assert.deepEqual(filterSessions(sessions, [], "november").map((s) => s.id), ["b"]);
});

test("an empty query is not a filter, and names still match", () => {
  assert.equal(filterSessions(sessions, [], "   ").length, 2);
  assert.deepEqual(filterSessions(sessions, [], "pipeline").map((s) => s.id), ["b"]);
});

// The two boxes drifted once: the sidebar learned dates and the chat picker
// kept matching names alone, so the same query found different sessions
// depending on which box you typed it into. One implementation, imported by
// both, is what stops that recurring.
test("both session search boxes use this module and the same hint", async () => {
  for (const path of ["../components/Layout.tsx", "../components/PostCall/MeetingChat.tsx"]) {
    const source = await read(path);
    assert.match(source, /from "\.\.?\/(\.\.\/)?lib\/sessionSearch"/, path);
    assert.match(source, /SEARCH_HINT/, path);
    assert.match(source, /aria-describedby/, path);
  }
  const hint = await read("../components/SearchHint.ts");
  assert.match(hint, /Search by date works too/);
});

test("neither box filters by name alone any more", async () => {
  const chat = await read("../components/PostCall/MeetingChat.tsx");
  assert.doesNotMatch(chat, /s\.name\.toLowerCase\(\)\.includes\(q\)/);
});
