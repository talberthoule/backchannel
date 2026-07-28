import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("voice enrollment uses live mic-only capture constraints", async () => {
  const { MIC_ONLY_AUDIO_CONSTRAINTS } = await import("./useAudioCapture.ts");

  assert.deepEqual(MIC_ONLY_AUDIO_CONSTRAINTS, {
    channelCount: 1,
    echoCancellation: false,
    noiseSuppression: false,
    autoGainControl: true,
  });
});

test("capture startup is single-flight and reusable after settlement", async () => {
  const captureModule = await import("./useAudioCapture.ts");
  assert.equal(typeof captureModule.startSingleFlight, "function");

  const inFlight = { current: null };
  let starts = 0;
  let finish;
  const operation = () => {
    starts += 1;
    return new Promise((resolve) => {
      finish = resolve;
    });
  };

  const first = captureModule.startSingleFlight(inFlight, operation);
  const second = captureModule.startSingleFlight(inFlight, operation);

  assert.strictEqual(second, first);
  assert.equal(starts, 1);

  finish();
  await first;

  const third = captureModule.startSingleFlight(inFlight, operation);
  assert.equal(starts, 2);
  finish();
  await third;
});

test("capture startup can retry after a rejected attempt", async () => {
  const { startSingleFlight } = await import("./useAudioCapture.ts");
  const inFlight = { current: null };
  let attempts = 0;
  const operation = () => {
    attempts += 1;
    return attempts === 1 ? Promise.reject(new Error("capture denied")) : Promise.resolve();
  };

  await assert.rejects(startSingleFlight(inFlight, operation), /capture denied/);
  await startSingleFlight(inFlight, operation);

  assert.equal(attempts, 2);
});

test("ending the share stops system frames and reports the track inactive", async () => {
  const { createSystemCaptureStop } = await import("./useAudioCapture.ts");

  let forwarding = true;
  const stopped = [];
  const states = [];
  const stop = createSystemCaptureStop({
    disconnect: () => { forwarding = false; },
    stream: { getTracks: () => [{ stop: () => stopped.push("audio") }, { stop: () => stopped.push("video") }] },
    notify: (active) => states.push(active),
  });

  // What the native "Stop sharing" bar reaches through the track's ended event.
  assert.equal(stop(), true);

  assert.equal(forwarding, false, "system frames must stop being forwarded");
  assert.deepEqual(states, [false], "the backend must be told the system track went inactive");
  assert.deepEqual(stopped, ["audio", "video"], "every display track is released");
});

test("ending the share twice reports the track inactive only once", async () => {
  const { createSystemCaptureStop } = await import("./useAudioCapture.ts");

  let disconnects = 0;
  const states = [];
  const stop = createSystemCaptureStop({
    disconnect: () => { disconnects += 1; },
    stream: null,
    notify: (active) => states.push(active),
  });

  assert.equal(stop(), true);
  // The native bar, an explicit stop, and capture release can all land here.
  assert.equal(stop(), false);
  assert.equal(stop(), false);

  assert.equal(disconnects, 1);
  assert.deepEqual(states, [false]);
});

test("the display stream keeps a live track to carry the native stop signal", () => {
  const hook = readFileSync(new URL("./useAudioCapture.ts", import.meta.url), "utf8");

  // Chrome hangs the share's lifetime on the video track, and a track we stop
  // ourselves never fires "ended", so stopping it here would discard the only
  // signal that the user ended the share.
  assert.match(hook, /getVideoTracks\(\)\.forEach\(\(track\) => \{ track\.enabled = false; \}\)/);
  assert.doesNotMatch(hook, /getVideoTracks\(\)\.forEach\(\(track\) => track\.stop\(\)\)/);
  // Listen on every track, not just audio: which one ends first varies.
  assert.match(hook, /candidate\.getTracks\(\)\.forEach\(\(track\) => \{\s*track\.addEventListener\("ended", handleEnded/);
});

test("admin recorder cancels pending and active capture on unmount", () => {
  const card = readFileSync(
    new URL("../components/DiarizationCapabilityCard.tsx", import.meta.url),
    "utf8",
  );

  assert.match(card, /recordingGenerationRef\.current \+= 1/);
  assert.match(card, /recorder\.ondataavailable = null/);
  assert.match(card, /recorder\.onstop = null/);
  assert.match(card, /generation !== recordingGenerationRef\.current/);
});
