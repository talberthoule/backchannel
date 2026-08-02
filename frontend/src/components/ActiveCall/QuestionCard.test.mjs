import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const src = readFileSync(new URL("./QuestionCard.tsx", import.meta.url), "utf8");

const bundle = await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import QuestionCard from "./QuestionCard.tsx";
      import QuestionSummary from "../PostCall/QuestionSummary.tsx";

      const asked = {
        id: "asked-1", item_type: "asked", question: "What model?", rationale: "", source_context: "",
        vote: 0, starred: true, answered: false, dismissed: false,
        created_at: "2026-08-02T00:00:00Z", agent_source: "live_chat",
      };
      const noop = () => {};
      export const live = renderToStaticMarkup(React.createElement(QuestionCard, {
        question: asked, isStrategicSignal: true, onStar: noop, onDismiss: noop, onVote: noop,
      }));
      export const postCall = renderToStaticMarkup(React.createElement(QuestionSummary, {
        questions: [asked], speakers: [],
      }));
    `,
    resolveDir: dirname(fileURLToPath(new URL("./QuestionCard.tsx", import.meta.url))),
    sourcefile: "alp-243-render.tsx",
    loader: "tsx",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  write: false,
});

const compiled = { exports: {} };
new Function("require", "module", "exports", bundle.outputFiles[0].text)(
  createRequire(import.meta.url), compiled, compiled.exports,
);
const rendered = compiled.exports;

test("live_chat has an operator-facing agent label", () => {
  assert.match(src, /live_chat:\s*"You asked"/);
});

test("make directive is offered only on asked cards", () => {
  assert.match(src, /onMakeDirective/);
  assert.match(src, /itemType === "asked"/);
});

test("asked slugs use the theme foreground at every card and section render point", () => {
  for (const [surface, markup] of [["live", rendered.live], ["post-call", rendered.postCall]]) {
    const badge = markup.match(/<span[^>]*>You asked<\/span>/)?.[0];
    assert.ok(badge, `missing ${surface} asked badge`);
    assert.match(badge, /class="[^"]*\btext-brand-dark-gray\b[^"]*"/);
    assert.match(badge, /style="background-color:#47556915"/);
    assert.doesNotMatch(badge, /(?:style="|;)color:/);
  }

  const section = rendered.postCall.match(/<h3[^>]*>.*?Asked.*?<\/h3>/)?.[0];
  assert.ok(section, "missing asked section heading");
  assert.match(section, /^<h3 class="[^"]*\btext-brand-dark-gray\b[^"]*">/);
  assert.doesNotMatch(section, /style="color:#475569"/);

  const count = section.match(/<span[^>]*>1<\/span>/)?.[0];
  assert.ok(count, "missing asked section count");
  assert.match(count, /class="[^"]*\btext-brand-dark-gray\b[^"]*"/);
  assert.match(count, /style="background-color:#47556915"/);
  assert.doesNotMatch(count, /(?:style="|;)color:/);
});
