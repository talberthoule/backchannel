import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const componentPath = fileURLToPath(new URL("./Layout.tsx", import.meta.url));
const outputDir = await mkdtemp(join(tmpdir(), "layout-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { DndContext } from "@dnd-kit/core";
      import {
        dateSearchTerms,
        deleteGroupWithConfirmation,
        DroppableGroup,
        filterSessions,
        orderSessions,
        pruneCollapsedGroups,
        readCollapsedGroups,
        scrollClosesMenu,
        sessionStateLabel,
        SEARCH_THRESHOLD,
      } from "./Layout.tsx";
      export { dateSearchTerms, deleteGroupWithConfirmation, filterSessions, orderSessions, pruneCollapsedGroups, readCollapsedGroups, scrollClosesMenu, sessionStateLabel, SEARCH_THRESHOLD };
      export function renderGroup(props) {
        return renderToStaticMarkup(
          React.createElement(
            DndContext,
            null,
            React.createElement(DroppableGroup, props),
          ),
        );
      }
    `,
    resolveDir: dirname(componentPath),
    sourcefile: "layout-test-entry.tsx",
    loader: "tsx",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: outputPath,
});

const {
  dateSearchTerms,
  deleteGroupWithConfirmation,
  filterSessions,
  orderSessions,
  pruneCollapsedGroups,
  readCollapsedGroups,
  renderGroup,
  scrollClosesMenu,
  sessionStateLabel,
  SEARCH_THRESHOLD,
} = createRequire(import.meta.url)(outputPath);

after(async () => {
  await rm(outputDir, { recursive: true, force: true });
});

const group = { id: "group-1", name: "Discovery" };
const dependencies = (overrides = {}) => ({
  confirm: async () => true,
  deleteGroup: async () => {},
  refreshGroups: () => {},
  refreshSessions: () => {},
  toast: () => {},
  ...overrides,
});

test("confirmed deletion uses the existing helper and refreshes both lists", async () => {
  const calls = [];
  let confirmation;

  await deleteGroupWithConfirmation(group, dependencies({
    confirm: async (options) => {
      confirmation = options;
      return true;
    },
    deleteGroup: async (id) => calls.push(["delete", id]),
    refreshGroups: () => calls.push(["groups"]),
    refreshSessions: () => calls.push(["sessions"]),
    toast: (message) => calls.push(["toast", message]),
  }));

  assert.match(confirmation.message, /will not be deleted/i);
  assert.match(confirmation.message, /move to Sessions/i);
  assert.equal(confirmation.confirmLabel, "Delete group");
  assert.deepEqual(calls, [
    ["delete", group.id],
    ["groups"],
    ["sessions"],
  ]);
});

test("cancelled deletion makes no request", async () => {
  let deleted = false;

  await deleteGroupWithConfirmation(group, dependencies({
    confirm: async () => false,
    deleteGroup: async () => { deleted = true; },
  }));

  assert.equal(deleted, false);
});

test("failed deletion stays retryable and does not refresh stale data", async () => {
  const calls = [];

  await deleteGroupWithConfirmation(group, dependencies({
    deleteGroup: async () => { throw new Error("offline"); },
    refreshGroups: () => calls.push("groups"),
    refreshSessions: () => calls.push("sessions"),
    toast: (message) => calls.push(message),
  }));

  assert.deepEqual(calls, [
    'Could not delete "Discovery". Check your connection and try again.',
  ]);
});

test("group delete button is named, revealed on hover or focus, and always present for touch", () => {
  const markup = renderGroup({
    group,
    children: null,
    isExpanded: true,
    onToggle: () => {},
    onDelete: () => {},
    sessionCount: 0,
  });

  assert.match(markup, /aria-label="Delete Discovery group"/);
  assert.match(markup, /title="Delete group"/);
  // The reveal class (index.css) hides it only until hover/focus-within and
  // never on touch screens; a bare opacity-0 would leave it unreachable there.
  assert.match(markup, /class="bc-reveal[^"]*"/);
  assert.doesNotMatch(markup, /opacity-0/);
  assert.match(markup, /aria-expanded="true"/);
  assert.match(markup, />No sessions</);
});

test("group toggle points aria-controls at a container that stays in the DOM when collapsed", () => {
  const props = {
    group,
    children: null,
    isExpanded: false,
    onToggle: () => {},
    onDelete: () => {},
    sessionCount: 0,
  };
  const collapsed = renderGroup(props);
  assert.match(collapsed, /aria-expanded="false"/);
  assert.match(collapsed, /aria-controls="bc-group-group-1-sessions"/);
  assert.match(collapsed, /id="bc-group-group-1-sessions"[^>]*hidden=""/);
  assert.doesNotMatch(collapsed, />No sessions</);

  const expanded = renderGroup({ ...props, isExpanded: true });
  assert.doesNotMatch(expanded, /hidden=""/);
  assert.match(expanded, />No sessions</);
});

test("the chevron reads as a control at rest, not only on hover", () => {
  // A bare glyph carrying no affordance is why the collapse control did not
  // read as usable (ALP-367). It sits on its own tinted square now, and that
  // square must not be behind the hover-reveal class.
  const markup = renderGroup({
    group,
    children: null,
    isExpanded: false,
    onToggle: () => {},
    onDelete: () => {},
    sessionCount: 0,
  });
  const chevronChip = markup.match(/<span class="([^"]*rounded bg-brand-light-gray-2[^"]*)"/);
  assert.ok(chevronChip, "the chevron should sit in a visible chip");
  assert.doesNotMatch(chevronChip[1], /bc-reveal/);
  assert.doesNotMatch(chevronChip[1], /opacity-0/);
});

test("collapsed groups are remembered as the exception, so an unlisted group is open", () => {
  // The polarity is the fix: at first paint the groups prop is still empty, so
  // an expanded-id set was empty too and every group came up collapsed.
  const stored = new Set(["g2"]);
  assert.equal(stored.has("g1"), false, "g1 was never collapsed, so it is open");
  assert.equal(stored.has("g2"), true);
  // A group that arrives later needs no seeding at all.
  assert.equal(stored.has("g3-created-mid-session"), false);
});

test("pruneCollapsedGroups forgets deleted groups and keeps the set identity when nothing changed", () => {
  const collapsed = new Set(["g1", "gone"]);
  const pruned = pruneCollapsedGroups(collapsed, groups);
  assert.deepEqual([...pruned], ["g1"]);

  // Same set back when every id is still known: the persisting effect must
  // not see a new reference and loop.
  const clean = new Set(["g1"]);
  assert.equal(pruneCollapsedGroups(clean, groups), clean);
});

test("pruneCollapsedGroups treats an empty roster as not-yet-loaded, not as no groups", () => {
  // Groups are fetched asynchronously. Pruning against the empty first render
  // would wipe the user's choices on every reload.
  const collapsed = new Set(["g1"]);
  assert.equal(pruneCollapsedGroups(collapsed, []), collapsed);
});

test("readCollapsedGroups survives missing, unparsable, and wrong-shaped storage", () => {
  const original = globalThis.localStorage;
  const withStorage = (value) => {
    globalThis.localStorage = { getItem: () => value, setItem: () => {} };
    try {
      return readCollapsedGroups();
    } finally {
      globalThis.localStorage = original;
    }
  };

  assert.deepEqual([...withStorage(null)], []);
  assert.deepEqual([...withStorage("not json")], []);
  assert.deepEqual([...withStorage('{"g1":true}')], []);
  assert.deepEqual([...withStorage('["g1", 7, "g2"]')], ["g1", "g2"]);
});

const session = (overrides) => ({
  id: "s",
  name: "Meeting",
  state: "completed",
  group_id: null,
  created_at: "2026-09-01T00:00:00Z",
  started_at: null,
  ended_at: null,
  notes: null,
  meeting_type: "general",
  meeting_context: "",
  speaker_context_dirty: false,
  speaker_context_enhanced_at: null,
  ...overrides,
});

const sessions = [
  session({ id: "a", name: "Meeting Aug 24, 1:00 PM", group_id: "g1" }),
  session({ id: "b", name: "Purdue kickoff", group_id: "g2" }),
  session({ id: "c", name: "Metlife renewal", group_id: null }),
];
const groups = [
  { id: "g1", name: "EA & Digital", display_order: 0, created_at: "" },
  { id: "g2", name: "Purdue", display_order: 1, created_at: "" },
];

test("filterSessions returns the list untouched for an empty or blank query", () => {
  assert.equal(filterSessions(sessions, groups, ""), sessions);
  assert.equal(filterSessions(sessions, groups, "   "), sessions);
});

test("filterSessions matches session names case-insensitively", () => {
  assert.deepEqual(filterSessions(sessions, groups, "METLIFE").map((s) => s.id), ["c"]);
  assert.deepEqual(filterSessions(sessions, groups, "aug 24").map((s) => s.id), ["a"]);
});

test("filterSessions also matches on the session's group name", () => {
  assert.deepEqual(filterSessions(sessions, groups, "digital").map((s) => s.id), ["a"]);
  // "purdue" hits both the group and a session name; each session once.
  assert.deepEqual(filterSessions(sessions, groups, "purdue").map((s) => s.id), ["b"]);
});

test("filterSessions returns nothing when nothing matches", () => {
  assert.deepEqual(filterSessions(sessions, groups, "zzz"), []);
});

// Noon UTC keeps the local calendar date stable in every time zone a test
// machine is likely to sit in.
const dated = [
  session({ id: "oct8", name: "Renewal review", created_at: "2026-10-08T12:00:00Z" }),
  session({ id: "oct18", name: "Board prep", created_at: "2026-10-18T12:00:00Z" }),
  session({ id: "aug3", name: "Kickoff", created_at: "2026-07-30T12:00:00Z", started_at: "2026-08-03T12:00:00Z" }),
];

test("dateSearchTerms spells a date every way a person might type it", () => {
  const terms = dateSearchTerms("2026-10-08T12:00:00Z");
  for (const expected of ["october", "oct", "8", "08", "10/8", "10/08", "10-8", "10-08", "2026-10-08", "oct 8", "october 8", "8-oct", "10/8/2026", "2026"]) {
    assert.ok(terms.includes(expected), `missing ${expected}`);
  }
  assert.deepEqual(dateSearchTerms(null), []);
  assert.deepEqual(dateSearchTerms("not a date"), []);
});

test("filterSessions matches hidden date metadata by prefix", () => {
  const ids = (query) => filterSessions(dated, groups, query).map((s) => s.id);
  assert.deepEqual(ids("October"), ["oct8", "oct18"]);
  assert.deepEqual(ids("oct 8"), ["oct8"]);
  assert.deepEqual(ids("8"), ["oct8", "aug3"]);
  assert.deepEqual(ids("08"), ["oct8", "aug3"]);
  assert.deepEqual(ids("8-"), ["oct8", "aug3"]);
  assert.deepEqual(ids("8/"), ["aug3"]);
  assert.deepEqual(ids("10/8"), ["oct8"]);
  assert.deepEqual(ids("10-18"), ["oct18"]);
  assert.deepEqual(ids("2026-10-08"), ["oct8"]);
  // The start date counts as well as the creation date.
  assert.deepEqual(ids("aug"), ["aug3"]);
  assert.deepEqual(ids("july"), ["aug3"]);
  // A bare digit inside a name still only matches the name by substring.
  assert.deepEqual(ids("board"), ["oct18"]);
});

test("orderSessions puts live sessions first and otherwise keeps order", () => {
  const list = [
    session({ id: "1", state: "completed" }),
    session({ id: "2", state: "active" }),
    session({ id: "3", state: "pre_call" }),
    session({ id: "4", state: "active" }),
  ];
  assert.deepEqual(orderSessions(list).map((s) => s.id), ["2", "4", "1", "3"]);
  // Pure: the input is not reordered.
  assert.deepEqual(list.map((s) => s.id), ["1", "2", "3", "4"]);
});

test("sessionStateLabel names every state in plain words", () => {
  assert.equal(sessionStateLabel("pre_call"), "Not started");
  assert.equal(sessionStateLabel("active"), "Live");
  assert.equal(sessionStateLabel("completed"), "Completed");
});

test("the find box threshold is a small handful", () => {
  assert.ok(SEARCH_THRESHOLD >= 4 && SEARCH_THRESHOLD <= 8);
});

test("a scroll closes the row menu unless it happened inside the menu's own list", () => {
  const inner = { nodeType: 1 };
  const outer = { nodeType: 1 };
  const documentNode = { nodeType: 9 };
  const menu = { contains: (node) => node === inner };

  // Wheel-scrolling a Move to list taller than the viewport must keep it open.
  assert.equal(scrollClosesMenu(menu, inner), false);
  // The session list, the page, or anything else scrolling leaves the fixed
  // menu floating, so those close it.
  assert.equal(scrollClosesMenu(menu, outer), true);
  assert.equal(scrollClosesMenu(menu, documentNode), true);
  // Defensive defaults: no menu element or no target still closes.
  assert.equal(scrollClosesMenu(null, inner), true);
  assert.equal(scrollClosesMenu(menu, null), true);
  assert.equal(scrollClosesMenu(menu, { notANode: true }), true);
});
