# ALP-120 Group Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make group deletion visible, confirmed, recoverable on failure, and immediately reflected in the sidebar.

**Architecture:** Keep the existing API endpoint and helper. Add one testable action function and one small delete-button component inside `Layout.tsx`, wired to the existing `ConfirmProvider`; keep backend production code unchanged and add focused endpoint coverage.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, Node `node:test`, FastAPI, SQLAlchemy, stdlib `unittest`.

## Global Constraints

- Use `DELETE /api/groups/{group_id}` through the existing `api.deleteGroup`.
- Deleting a group ungroups contained sessions and never deletes them.
- Reuse `ConfirmProvider`; add no modal, menu, dependency, or endpoint.
- Refresh groups and sessions only after a successful delete.
- Keep the action keyboard accessible and always visible in the expanded sidebar.

---

### Task 1: Frontend delete interaction

**Files:**
- Create: `frontend/src/components/Layout.test.mjs`
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/package.json`

**Interfaces:**
- Produces: `deleteGroupWithConfirmation(group, deps): Promise<boolean>`
- Produces: `GroupDeleteButton({ group, deleting, onDelete }): React.ReactElement`
- Consumes: existing `useConfirm()`, `api.deleteGroup`, `onRefreshGroups`, and `onRefreshSessions`

- [ ] **Step 1: Write the failing interaction and markup tests**

Bundle `Layout.tsx` with esbuild, export the two interfaces above, and assert:

```js
test("confirmed deletion calls the existing helper and refreshes groups and sessions", async () => {
  const calls = [];
  const result = await deleteGroupWithConfirmation(group, {
    confirm: async (options) => {
      assert.match(options.message, /will not be deleted/i);
      return true;
    },
    deleteGroup: async (id) => calls.push(["delete", id]),
    refreshGroups: () => calls.push(["groups"]),
    refreshSessions: () => calls.push(["sessions"]),
    toast: () => calls.push(["toast"]),
  });
  assert.equal(result, true);
  assert.deepEqual(calls, [["delete", group.id], ["groups"], ["sessions"]]);
});
```

Also assert cancellation makes no delete call, rejection emits retry-oriented
toast copy without refreshing, and the rendered button has an accessible label,
tooltip, visible classes, and disabled state.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
node --test src/components/Layout.test.mjs
```

Expected: FAIL because `deleteGroupWithConfirmation` and
`GroupDeleteButton` are not exported.

- [ ] **Step 3: Implement the minimal interaction**

In `Layout.tsx`, import `useConfirm`, add the two tested exports, add
`deletingGroupId` state, and replace the hidden X control with
`GroupDeleteButton`. Use this confirmation:

```ts
{
  title: `Delete ${group.name}?`,
  message: "Sessions in this group will move to Sessions and will not be deleted.",
  confirmLabel: "Delete group",
  tone: "danger",
}
```

On rejection, call:

```ts
toast(`Could not delete "${group.name}". Check your connection and try again.`);
```

Add `src/components/Layout.test.mjs` to the existing `npm test` command.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```powershell
npm test
```

Expected: all frontend tests pass, including the new group-delete cases.

### Task 2: Backend ungrouping coverage

**Files:**
- Create: `backend/tests/test_groups.py`
- Read only: `backend/app/routers/groups.py`

**Interfaces:**
- Consumes: existing `delete_group(group_id, db)`
- Produces: regression coverage only; no production interface

- [ ] **Step 1: Add the focused endpoint test**

Create a fake async session that records `execute`, `delete`, and `commit`.
Call `delete_group`, compile the recorded SQLAlchemy update, and assert it sets
`Session.group_id` to `NULL` for the requested group. Assert the only object
passed to `db.delete` is the `SessionGroup`, followed by one commit.

- [ ] **Step 2: Run the focused backend test**

Run:

```powershell
python -m unittest tests.test_groups
```

Expected: one focused test passes against the existing endpoint.

### Task 3: Verification and handoff

**Files:**
- Verify all files above

- [ ] **Step 1: Run required gates**

Run:

```powershell
python -m unittest tests.test_groups
cd ../frontend
npm test
npm run build
```

Expected: backend group tests pass, all frontend tests pass, and Vite build
exits zero.

- [ ] **Step 2: Commit**

Stage only ALP-120 files and commit:

```powershell
git commit -m "feat: make sidebar groups safely deletable"
```

- [ ] **Step 3: Update Linear and report**

Comment on ALP-120 with the branch, SHA, focused test counts, build result, and
confirmation that master and remotes were untouched. Send the same substantive
branch-ready handoff to `w2:p9`.
