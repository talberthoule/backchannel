import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const src = readFileSync(new URL("./DirectiveBar.tsx", import.meta.url), "utf8");

// Real-render harness (matches ActiveCallView.test.mjs's sibling pattern):
// the askDisabled fix (ALP-178) is a rendered disabled attribute and
// placeholder text, which a source regex cannot see.
const componentPath = fileURLToPath(new URL("./DirectiveBar.tsx", import.meta.url));
const outputDir = await mkdtemp(join(tmpdir(), "directive-bar-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import DirectiveBar from "./DirectiveBar.tsx";
      export function render(props) {
        return renderToStaticMarkup(React.createElement(DirectiveBar, props));
      }
    `,
    resolveDir: dirname(componentPath),
    sourcefile: "directive-bar-test-entry.tsx",
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

const noop = () => {};

function barProps(overrides = {}) {
  return {
    onAddDirective: noop,
    onAsk: noop,
    models: [],
    modelId: "",
    onModelChange: noop,
    localOnly: false,
    ...overrides,
  };
}

test("the bar defaults to chat mode", () => {
  assert.match(src, /useState<Mode>\(\s*(\(\)\s*=>\s*)?[^)]*"chat"/);
});

test("the input is always open, not behind an expand button", () => {
  assert.ok(!/setExpanded/.test(src), "expand/collapse state should be gone");
  assert.match(src, /<input/);
});

test("mode persists across sessions", () => {
  assert.match(src, /localStorage/);
});

test("both modes are reachable", () => {
  assert.match(src, /Directive/);
  assert.match(src, /Chat/);
});

test("the model chip is rendered", () => {
  assert.match(src, /<ModelChip/);
});

test("a second submit is ignored while an ask is already in flight", () => {
  assert.match(src, /if\s*\(!modelId\s*\|\|\s*asking\)\s*return;/);
});

test("askDisabled blocks the chat input and never reaches onAsk (ALP-178)", () => {
  // A tab that lost its runtime (a refresh, a second tab) cannot confirm an
  // ask reaches the call it looks like it is asking, so no request should
  // fire at all - not even a masked one. Render proof: with no mode prop
  // the bar always mounts in chat (default), and Node has no
  // window.localStorage to override that, so this is the chat-mode render.
  const html = render(barProps({ askDisabled: true }));
  assert.match(html, /disabled=""/);
  assert.match(html, /Resume audio to ask\.\.\./);

  // Directive mode is structurally unaffected: both the disabled attribute
  // and the placeholder gate askDisabled behind chatMode, so switching mode
  // (an internal, localStorage-backed state this static render cannot
  // trigger) is the only way askDisabled ever applies.
  assert.match(src, /disabled=\{disabled \|\| \(chatMode && askDisabled\)\}/);
  assert.match(src, /chatMode && askDisabled/);

  // The guard itself returns before onAsk and before clearing the input.
  assert.match(src, /if\s*\(askDisabled\)\s*return;/);
});
