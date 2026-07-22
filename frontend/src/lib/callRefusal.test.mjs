import assert from "node:assert/strict";
import test from "node:test";

const load = () => import("./callRefusal.ts");

test("refused fresh call rolls back to pre-call setup", async () => {
  const { refusalRollbackState } = await load();
  assert.equal(
    refusalRollbackState({ state: "active", ended_at: null }, 0),
    "pre_call",
  );
});

test("refused session with a surviving ended_at rolls back to completed", async () => {
  const { refusalRollbackState } = await load();
  assert.equal(
    refusalRollbackState({ state: "active", ended_at: "2026-07-22T00:00:00Z" }, 0),
    "completed",
  );
});

test("refused resume of a completed zero-segment imported session stays completed", async () => {
  const { refusalRollbackState } = await load();
  // The resume PATCH cleared ended_at; imported sessions have transcript
  // entries but no call segments.
  assert.equal(
    refusalRollbackState({ state: "active", ended_at: null }, 42),
    "completed",
  );
});

test("reconcile is a no-op when the server already restored the session", async () => {
  const { reconcileRefusedSession } = await load();
  const patches = [];
  const problem = await reconcileRefusedSession("s1", 0, {
    getSession: async () => ({ state: "pre_call", ended_at: null }),
    updateSession: async (id, data) => {
      patches.push([id, data]);
    },
  });
  assert.equal(problem, null);
  assert.deepEqual(patches, []);
});

test("reconcile patches a still-active imported session back to completed", async () => {
  const { reconcileRefusedSession } = await load();
  const patches = [];
  const problem = await reconcileRefusedSession("s1", 3, {
    getSession: async () => ({ state: "active", ended_at: null }),
    updateSession: async (id, data) => {
      patches.push([id, data]);
    },
  });
  assert.equal(problem, null);
  assert.deepEqual(patches, [["s1", { state: "completed" }]]);
});

test("reconcile patches a still-active fresh session back to pre-call", async () => {
  const { reconcileRefusedSession } = await load();
  const patches = [];
  const problem = await reconcileRefusedSession("s1", 0, {
    getSession: async () => ({ state: "active", ended_at: null }),
    updateSession: async (id, data) => {
      patches.push([id, data]);
    },
  });
  assert.equal(problem, null);
  assert.deepEqual(patches, [["s1", { state: "pre_call" }]]);
});

test("reconcile surfaces update failures instead of suppressing them", async () => {
  const { reconcileRefusedSession } = await load();
  const problem = await reconcileRefusedSession("s1", 0, {
    getSession: async () => ({ state: "active", ended_at: null }),
    updateSession: async () => {
      throw new Error("PATCH 500");
    },
  });
  assert.equal(problem, "PATCH 500");
});

test("reconcile surfaces read failures instead of suppressing them", async () => {
  const { reconcileRefusedSession } = await load();
  const problem = await reconcileRefusedSession("s1", 0, {
    getSession: async () => {
      throw new Error("network down");
    },
    updateSession: async () => {},
  });
  assert.equal(problem, "network down");
});
