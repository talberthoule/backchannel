// The meter paints itself from an animation frame instead of through React
// (ALP-291), which only stays correct while three things hold: the bar class is
// fixed at compile time, the level prop keeps one object identity, and the
// effect cancels the frame it scheduled. Each of those fails silently - the
// build stays green and the meter quietly stops moving - so they are pinned
// here.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";
import { build } from "esbuild";

const componentPath = fileURLToPath(new URL("./AudioIndicator.tsx", import.meta.url));
const viewSource = readFileSync(new URL("./ActiveCallView.tsx", import.meta.url), "utf8");
const appSource = readFileSync(new URL("../../App.tsx", import.meta.url), "utf8");
const componentSource = readFileSync(componentPath, "utf8");

const outputDir = await mkdtemp(join(tmpdir(), "audio-indicator-test-"));

// Bundle 1: the real React, rendered to static markup.
const markupPath = join(outputDir, "markup.cjs");
await build({
  stdin: {
    contents: `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import AudioIndicator from "./AudioIndicator.tsx";
      export function renderMeter(props) {
        return renderToStaticMarkup(React.createElement(AudioIndicator, props));
      }
    `,
    resolveDir: dirname(componentPath),
    sourcefile: "audio-indicator-markup-entry.tsx",
    loader: "tsx",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: markupPath,
});

// Bundle 2: React replaced by a probe, so the animation frame effect can be
// driven by hand and every re-render React would do is counted.
const probePath = join(outputDir, "react-probe.mjs");
await writeFile(probePath, `
export const hooks = { cells: [], index: 0, effects: [], setStateCalls: 0, useStateCalls: 0 };
export function useRef(initial) {
  const i = hooks.index++;
  if (!(i in hooks.cells)) hooks.cells[i] = { current: initial };
  return hooks.cells[i];
}
export function useEffect(fn) { hooks.effects.push(fn); }
export function useState(initial) {
  hooks.useStateCalls += 1;
  const i = hooks.index++;
  if (!(i in hooks.cells)) hooks.cells[i] = { value: initial };
  const cell = hooks.cells[i];
  return [cell.value, (next) => { hooks.setStateCalls += 1; cell.value = next; }];
}
export function useMemo(fn) { return fn(); }
export function useCallback(fn) { return fn; }
export function jsx(type, props) {
  const { children, ...rest } = props || {};
  const list = children === undefined ? [] : [].concat(children);
  return { type, props: rest, children: list.flat() };
}
export const jsxs = jsx;
export const jsxDEV = jsx;
export const Fragment = Symbol("Fragment");
`);

const framesPath = join(outputDir, "frames.cjs");
await build({
  stdin: {
    contents: `
      export { default as AudioIndicator } from "./AudioIndicator.tsx";
      export { hooks } from "react";
    `,
    resolveDir: dirname(componentPath),
    sourcefile: "audio-indicator-frames-entry.tsx",
    loader: "tsx",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: framesPath,
  alias: { react: probePath, "react/jsx-runtime": probePath },
});

const load = createRequire(import.meta.url);
const { renderMeter } = load(markupPath);
const { AudioIndicator, hooks } = load(framesPath);

after(async () => {
  await rm(outputDir, { recursive: true, force: true });
});

// --- hand-driven animation frames -------------------------------------------

const frames = new Map();
let nextFrameId = 1;
let clockNow = performance.now();
globalThis.requestAnimationFrame = (cb) => {
  const id = nextFrameId++;
  frames.set(id, cb);
  return id;
};
globalThis.cancelAnimationFrame = (id) => {
  frames.delete(id);
};

function runFrames(count) {
  for (let i = 0; i < count; i++) {
    clockNow += 1000 / 60;
    const pending = [...frames.values()];
    frames.clear();
    for (const cb of pending) cb(clockNow);
  }
}

function makeNode(className) {
  const classes = new Set(String(className || "").split(/\s+/).filter(Boolean));
  return {
    classes,
    attrs: {},
    attrWrites: 0,
    classList: {
      toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
    setAttribute(name, value) {
      this.attrs[name] = value;
      this.attrWrites += 1;
    },
  };
}

/** Renders the component by hand, keeping DOM nodes across renders as React does. */
function mountMeter(props) {
  hooks.cells.length = 0;
  hooks.setStateCalls = 0;
  hooks.useStateCalls = 0;

  const nodes = [];
  let cleanups = [];
  let renders = 0;

  const attach = (node, slot) => {
    if (!node || typeof node !== "object") return slot;
    const { props: nodeProps = {}, children = [] } = node;
    if (nodeProps.ref) {
      if (!nodes[slot]) nodes[slot] = makeNode(nodeProps.className);
      const el = nodes[slot];
      slot += 1;
      if (typeof nodeProps.ref === "function") nodeProps.ref(el);
      else nodeProps.ref.current = el;
    }
    for (const child of children) slot = attach(child, slot);
    return slot;
  };

  const paint = (next) => {
    for (const cleanup of cleanups) if (typeof cleanup === "function") cleanup();
    hooks.index = 0;
    hooks.effects = [];
    renders += 1;
    attach(AudioIndicator(next), 0);
    cleanups = hooks.effects.map((fn) => fn());
  };

  paint(props);
  return {
    rerender: paint,
    unmount: () => {
      for (const cleanup of cleanups) if (typeof cleanup === "function") cleanup();
      cleanups = [];
    },
    get meter() { return nodes[0]; },
    get bars() { return nodes.slice(1); },
    get renders() { return renders; },
    litBars: () => nodes.slice(1).filter((bar) => bar.classes.has("bg-green-500")).length,
  };
}

// --- render output ----------------------------------------------------------

function barClasses(markup) {
  return [...markup.matchAll(/class="([^"]*\bw-1\b[^"]*)"/g)].map((m) => m[1]);
}

const LABEL = "Microphone input level";

test("the bar class is identical for every prop combination React can re-render with", () => {
  // React writes className only when the string changes between renders. If any
  // prop reaches it, a parent re-render wipes the classes the frame just wrote
  // and the meter freezes until the bar count next changes.
  const variants = [
    { isCapturing: true, level: { current: 0 }, label: LABEL },
    { isCapturing: false, level: { current: 0 }, label: LABEL },
    { isCapturing: true, level: { current: 1 }, label: "Meeting audio input level" },
    { isCapturing: false, level: { current: 0.42 }, label: "Meeting audio input level" },
  ];

  const seen = new Set();
  for (const variant of variants) {
    const bars = barClasses(renderMeter(variant));
    assert.equal(bars.length, 5, "five bars render");
    assert.equal(new Set(bars).size, 1, "all five bars share one class string");
    seen.add(bars[0]);
  }

  assert.equal(seen.size, 1, "bar class must not depend on any prop");
  const barClass = [...seen][0];
  assert.match(barClass, /bg-brand-light-gray-1/, "bars render idle");
  assert.doesNotMatch(barClass, /bg-green-500/, "lit state is never rendered by React");
});

test("the bar className is one constant, with no interpolation React could vary", () => {
  const template = componentSource.match(/className=\{`(w-1[^`]*)`\}/);
  assert.ok(template, "bar className template literal found");
  assert.deepEqual(
    template[1].match(/\$\{[^}]*\}/g) ?? [],
    ["${IDLE_BAR_CLASS}"],
    "the only interpolation may be the module-level idle class",
  );
});

test("the level never reaches the render output", () => {
  const quiet = renderMeter({ isCapturing: true, level: { current: 0 }, label: LABEL });
  const loud = renderMeter({ isCapturing: true, level: { current: 1 }, label: LABEL });
  assert.equal(quiet, loud, "markup must not encode the live level");
  assert.match(quiet, /role="meter"/);
  assert.match(quiet, /aria-valuemin="0"/);
  assert.match(quiet, /aria-valuemax="100"/);
  assert.match(quiet, /aria-valuenow="0"/);
});

test("each meter is named by its own prop", () => {
  assert.match(renderMeter({ isCapturing: true, level: { current: 0 }, label: LABEL }), /aria-label="Microphone input level"/);
  assert.match(
    renderMeter({ isCapturing: true, level: { current: 0 }, label: "Meeting audio input level" }),
    /aria-label="Meeting audio input level"/,
  );
  assert.doesNotMatch(componentSource, /aria-label="/, "the name is never hardcoded");

  // Two meters can be on screen at once; identical names are indistinguishable.
  const labels = [...viewSource.matchAll(/\slabel="([^"]+)"/g)].map((m) => m[1]);
  assert.equal(labels.length, 2, "both AudioIndicator call sites pass a name");
  assert.equal(new Set(labels).size, 2, "the two meters must not share a name");
});

// --- stable level identity --------------------------------------------------

test("call sites pass a stable level object, never a fresh literal", () => {
  // A new object per render restarts the effect on every parent render and
  // strands the meter on a source nothing writes to.
  for (const [name, source] of [["App.tsx", appSource], ["ActiveCallView.tsx", viewSource]]) {
    assert.doesNotMatch(
      source,
      /(?:audioLevel|systemAudioLevel|level)=\{\{/,
      `${name} must not pass an inline object as a meter level`,
    );
  }

  assert.match(appSource, /audioLevel=\{audioLevelRef\}/);
  assert.match(appSource, /systemAudioLevel=\{[^{}]*systemAudioLevelRef[^{}]*SILENT_AUDIO_LEVEL\}/);
  assert.match(viewSource, /level=\{audioLevel\}/);
  assert.match(viewSource, /level=\{systemAudioLevel \?\? SILENT_AUDIO_LEVEL\}/);
  assert.match(componentSource, /\}, \[isCapturing, level\]\);/, "the frame effect keys off level identity");
});

test("the silent stand-in is one shared zero", async () => {
  const first = await import("../../hooks/useAudioCapture.ts");
  const second = await import("../../hooks/useAudioCapture.ts");
  assert.strictEqual(first.SILENT_AUDIO_LEVEL, second.SILENT_AUDIO_LEVEL);
  assert.equal(first.SILENT_AUDIO_LEVEL.current, 0);
});

// --- animation frame behaviour ----------------------------------------------

test("the meter animates without asking React to re-render", () => {
  const level = { current: 0 };
  const meter = mountMeter({ isCapturing: true, level, label: LABEL });

  let changes = 0;
  let last = meter.litBars();
  for (let i = 0; i < 300; i++) {
    level.current = Math.abs(Math.sin(i / 9));
    runFrames(1);
    const lit = meter.litBars();
    if (lit !== last) changes += 1;
    last = lit;
  }

  assert.equal(meter.renders, 1, "300 frames caused no re-render");
  assert.equal(hooks.useStateCalls, 0, "the meter holds no React state");
  assert.equal(hooks.setStateCalls, 0, "no state update escapes the frame loop");
  assert.ok(changes > 30, `meter should still animate, saw ${changes} changes`);

  level.current = 1;
  runFrames(1);
  assert.equal(meter.litBars(), 5, "peak level lights every bar");
  level.current = 0;
  runFrames(1);
  assert.equal(meter.litBars(), 0, "silence lights no bars");
  meter.unmount();
});

test("aria-valuenow keeps a human update rate", () => {
  const level = { current: 0 };
  const meter = mountMeter({ isCapturing: true, level, label: LABEL });
  const before = meter.meter.attrWrites;

  const frameCount = 300;
  for (let i = 0; i < frameCount; i++) {
    level.current = Math.abs(Math.sin(i / 9));
    runFrames(1);
  }

  const perSecond = (meter.meter.attrWrites - before) / (frameCount / 60);
  assert.ok(perSecond >= 4, `announced value should stay live, saw ${perSecond}Hz`);
  assert.ok(perSecond <= 10, `announced value should not flood at frame rate, saw ${perSecond}Hz`);
  meter.unmount();
});

test("stopping capture clears the bars and announces zero", () => {
  const level = { current: 0.9 };
  const meter = mountMeter({ isCapturing: true, level, label: LABEL });
  runFrames(20);
  assert.ok(meter.litBars() > 0, "bars light while capturing");

  meter.rerender({ isCapturing: false, level, label: LABEL });
  assert.equal(meter.litBars(), 0, "no capture means no lit bars");
  assert.equal(meter.meter.attrs["aria-valuenow"], "0", "no capture means no announced level");
  meter.unmount();
});

test("every scheduled frame is cancelled when the effect tears down", () => {
  const level = { current: 0.5 };
  const meter = mountMeter({ isCapturing: true, level, label: LABEL });
  assert.equal(frames.size, 1, "capturing schedules exactly one frame");

  for (let i = 0; i < 5; i++) {
    meter.rerender({ isCapturing: false, level, label: LABEL });
    assert.equal(frames.size, 0, "idle meters schedule nothing");
    meter.rerender({ isCapturing: true, level, label: LABEL });
    assert.equal(frames.size, 1, "toggling capture must not stack frame loops");
  }

  meter.unmount();
  assert.equal(frames.size, 0, "unmount cancels the frame");

  const quiet = meter.meter.attrWrites;
  const litAtUnmount = meter.litBars();
  level.current = 1;
  runFrames(60);
  assert.equal(meter.meter.attrWrites, quiet, "an unmounted meter writes nothing");
  assert.equal(meter.litBars(), litAtUnmount, "an unmounted meter paints nothing");
});
