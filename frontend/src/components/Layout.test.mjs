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
        deleteGroupWithConfirmation,
        DroppableGroup,
      } from "./Layout.tsx";
      export { deleteGroupWithConfirmation };
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

const { deleteGroupWithConfirmation, renderGroup } =
  createRequire(import.meta.url)(outputPath);

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

test("group delete button is visible and named", () => {
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
  assert.doesNotMatch(markup, /opacity-0/);
});
