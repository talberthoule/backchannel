import assert from "node:assert/strict";
import test from "node:test";

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
