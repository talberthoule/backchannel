# Development handoff - 2026-09-11

## Branch and review

- Continue on `agent/alp-396-live-insight-paging`, not `master`.
- Implementation commit: `64804339b3fa500db265c599b70dcd80000354a2`.
- ALP-396 in Linear contains the diagnosis, implementation rationale, and tab 3's
  APPROVE review. The reviewer reported status In Review.
- This handoff and the mock/backlog are a separate follow-up commit on that branch.
- Push is authorized; merge and release are not. The installed v0.6.5 desktop app
  does not receive this fix just because the source is pushed.

## Implemented

- Live insights mount at most 40 cards per page with First/Previous/Next/Last.
- Transcript shows a rolling 40-entry live tail or a held history window, with
  First/Older/Newer/Live controls. Search covers the entire transcript and mounts
  the window containing the active match.
- App memoizes insight and transcript collections; unchanged rows skip rendering.
- Date formatters are reused, and interim speech is explicitly marked client-side.
- Existing styling and keyboard search/navigation are preserved.

Verification at the implementation commit: 236 frontend tests passed (17 added),
both isolated browser harnesses passed at up to 10,000 entries, and the production
build passed. Sentrux check reports only the two documented generated-lockfile
size exceptions. Tab 3 independently reported that the gate has no degradation.

Non-blocking review notes: a search match in the moving live window can re-center
on new entries; the previous new-insight slide-in animation was removed. Neither
blocks the approval. Unbounded WebSocket message retention remains follow-up work.

## Continue on another computer

```powershell
git clone --branch agent/alp-396-live-insight-paging https://github.com/talberthoule/backchannel.git
cd backchannel/frontend
npm ci
npm test
npm run build
```

Use Node 24 as declared in `frontend/package.json`. See `AGENTS.md` for backend,
database, Docker, model downloads, and normal development setup. Browser harnesses
require an installed Playwright package and its Chromium browser; supply the
package path as an argument, or use normal module resolution:

```powershell
node scripts/test-insight-paging.mjs <path-to-playwright>
node scripts/test-transcript-paging.mjs <path-to-playwright>
```

These harnesses use synthetic data and never connect to a real call. They require
the preceding frontend build for CSS. Do not commit machine-specific package paths.

## Backlog and commitments mock

- `docs/plans/2026-09-10-enhancement-backlog.md`: seven enhancement drafts, now
  annotated with ALP-396's completed rendering scope and remaining retention work.
- `output/commitments-mock/commitments.html`: editable, fictional-data concept.
- `output/commitments-mock/preview.html`: standalone host for the concept.
- `output/commitments-mock/check.cjs`: optional browser interaction checks.

From the repository root, serve the concept locally:

```powershell
python -m http.server 4178 --bind 127.0.0.1 --directory output/commitments-mock
```

Open `http://127.0.0.1:4178/preview.html`. The standalone host loads supporting
scripts from public CDNs. Optional checks:

```powershell
node output/commitments-mock/check.cjs <path-to-playwright>
node output/commitments-mock/check.cjs <path-to-playwright> --host
```

The mock is not a production feature. Its original owner dropdown still needs
manual entry: users MUST be able to select a captured name OR type a corrected or
new name, including when no speakers were captured. Human edits must survive
reloads and later analysis. This requirement is explicit in backlog item 1.

## Deliberately not transferred through GitHub

- Generated screenshots under `output/`; the checks can regenerate them.
- Provider credentials, `.env`, local databases, meeting recordings, and installed
  model/runtime files. Provision or securely transfer these separately as needed.
- Agent chat history and machine-specific Herdr/skill installations; this document
  records the relevant decisions instead.
- Older local-only branches/worktrees outside this task. Their equivalence to
  merged work has not been audited; this handoff is not a whole-machine backup.
