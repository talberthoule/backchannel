import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";
import { readFileSync } from "node:fs";

const componentPath = fileURLToPath(new URL("./LanguageSelector.tsx", import.meta.url));
const outputDir = await mkdtemp(join(tmpdir(), "language-selector-test-"));
const outputPath = join(outputDir, "bundle.cjs");

await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import LanguageSelector from "./LanguageSelector.tsx";
      export function render() {
        return renderToStaticMarkup(React.createElement(LanguageSelector));
      }
    `,
    resolveDir: dirname(componentPath),
    sourcefile: "language-selector-test.tsx",
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

test("the Stage 1 selector advertises only completed English", () => {
  const markup = render();
  assert.match(markup, /aria-label="Language"/);
  assert.match(markup, /English/);
  assert.doesNotMatch(markup, /Deutsch|Français|Español|Português|简体中文|日本語|한국어|Русский|Polski|Türkçe|Català/);
  assert.match(markup, /<select/);
  assert.equal((markup.match(/<option/g) || []).length, 1);
});

test("language switching does not reload or remount application state", () => {
  const selector = readFileSync(componentPath, "utf8");
  const init = readFileSync(new URL("../i18n/index.ts", import.meta.url), "utf8");
  const main = readFileSync(new URL("../main.tsx", import.meta.url), "utf8");

  assert.doesNotMatch(selector, /location\.reload|window\.location/);
  assert.doesNotMatch(init, /location\.reload|window\.location/);
  assert.doesNotMatch(selector, /useSession|useWebSocket|useAudioCapture/);
  assert.match(main, /<App \/>/);
});
