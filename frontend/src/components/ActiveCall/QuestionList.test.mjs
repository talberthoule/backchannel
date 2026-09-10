import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const bundle = await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import QuestionList, { INSIGHT_PAGE_SIZE } from "./QuestionList.tsx";
      export { INSIGHT_PAGE_SIZE };
      const noop = () => {};
      export function render(questions) {
        return renderToStaticMarkup(React.createElement(QuestionList, {
          questions, onStar: noop, onDismiss: noop, onVote: noop,
        }));
      }
    `,
    resolveDir: dirname(fileURLToPath(import.meta.url)),
    loader: "tsx",
  },
  bundle: true, format: "cjs", platform: "node", write: false,
});
const compiled = { exports: {} };
new Function("require", "module", "exports", bundle.outputFiles[0].text)(
  createRequire(import.meta.url), compiled, compiled.exports,
);
const { render, INSIGHT_PAGE_SIZE } = compiled.exports;

function questions(count) {
  return Array.from({ length: count }, (_, i) => ({
    id: `insight-${i}`, question: `Insight number ${i}`, item_type: "observation",
    created_at: new Date(1700000000000 + i * 1000).toISOString(),
    starred: false, dismissed: false, answered: false, vote: 0,
  }));
}

for (const count of [0, 18, 40, 41, 860, 10000]) {
  test(`${count} insights mount at most ${INSIGHT_PAGE_SIZE} cards`, () => {
    const html = render(questions(count));
    assert.equal((html.match(/aria-label="Dismiss"/g) || []).length, Math.min(count, INSIGHT_PAGE_SIZE));
    assert.equal(html.includes('aria-label="Insight pages"'), count > INSIGHT_PAGE_SIZE);
    if (count > INSIGHT_PAGE_SIZE) assert.ok(html.includes(`1-40 of ${count} insights`));
  });
}

test("pinning and newest-first ordering apply before paging", () => {
  const items = questions(860);
  items[0].starred = true;
  const html = render(items);
  assert.ok(html.indexOf("Insight number 0<") < html.indexOf("Insight number 859<"));
  assert.ok(html.includes("Insight number 821<"));
  assert.ok(!html.includes("Insight number 820<"));
});

test("dismissed insights do not consume page slots or inflate the result count", () => {
  const items = questions(41);
  items[40].dismissed = true;
  const html = render(items);
  assert.equal((html.match(/aria-label="Dismiss"/g) || []).length, 40);
  assert.ok(!html.includes("Insight number 40<"));
  assert.ok(!html.includes('aria-label="Insight pages"'));
});
