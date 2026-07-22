import assert from "node:assert/strict";
import test from "node:test";

test("refused fresh call rolls back to pre-call setup", async () => {
  const { refusalRollbackState } = await import("./callRefusal.ts");
  assert.equal(refusalRollbackState(0), "pre_call");
});

test("refused resume rolls back to post-call review", async () => {
  const { refusalRollbackState } = await import("./callRefusal.ts");
  assert.equal(refusalRollbackState(3), "completed");
});
