# ALP-120 Group Delete Design

## Goal

Make the existing group deletion path discoverable and safe in the expanded
sidebar. Deleting a group must ungroup its sessions, not delete them.

## Chosen interaction

Keep the existing delete control in each group row, but make it always visible
when the sidebar is expanded. Give it a clear trash icon, tooltip, accessible
label, and keyboard focus. An overflow or context menu would add code while
making the action harder to discover.

Before calling the existing `api.deleteGroup`, use `ConfirmProvider` to explain
that the group will be deleted and its sessions will move to Sessions. Disable
the action while the request is running. On success, refresh groups and
sessions. On failure, leave the group in place and show a toast that says the
delete failed and can be retried.

## Data flow

1. User activates the visible delete action.
2. The shared confirmation dialog names the group and explains ungrouping.
3. Cancellation makes no request.
4. Confirmation calls the existing `DELETE /api/groups/{group_id}` helper.
5. Success refreshes groups and sessions.
6. Failure restores the action and shows retry-oriented feedback.

## Tests

- Frontend: cancellation, confirmation, both refresh callbacks, failure
  feedback, and discoverable accessible markup.
- Backend: the existing endpoint clears matching `Session.group_id` values,
  deletes only the `SessionGroup`, and commits.

No new endpoint, modal system, menu component, or persistent error model is in
scope.
