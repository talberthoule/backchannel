# Herdr workspace handoff — 2026-07-27

Written by the `claude` lane (pane `w2:pJ`) at the operator's request, so a second
machine and its Herdr agents can pick up this work without re-deriving it.

Everything below was verified against git, the running stack, or Linear at the time
of writing. Where something is a lane's own report that I did not independently
confirm, it says so.

---

## 1. Read this first: nothing is on origin

`origin/master` is **`f142913`**. Local `master` is **`f4c79b2`**, **29 commits ahead**,
and that gap holds a full day of work plus the entire ALP-150 desktop updater.

**The receiving machine cannot `git pull` this work.** Only two things are published:

| Ref | SHA | State |
| --- | --- | --- |
| `origin/master` | `f142913` | untouched all day |
| `origin/agent/alp-152-privacy-first-admits-self-hosted` | `2dec232` | **PR #27 open** |

So the handoff is not "clone and continue". Either the operator pushes the remaining
branches, or the new machine works from a bundle. See §7.

### Why it was deliberately held

ALP-150 (desktop updater, security-labelled) has **not** run CI or scanning, and its
macOS `ditto` extraction smoke is a **hard gate** before the first macOS auto-update
ships. It was held back on purpose. Do not publish it casually.

An earlier accident is worth knowing about: a lane branched from local `master` and
opened a PR, which published all 21 unpushed commits to a **public** repo. It was
closed and the branch deleted within ~40 minutes. No credential leaked — the only
key file, `desktop/release_signing_keys.json`, is the checked-in **public**
verification trust root by design (`update_signing.py` calls it "the exact checked-in
public-key document"). The lesson: **always check `origin/master..HEAD` before pushing.**

---

## 2. Local master commit train (origin → f4c79b2)

Newest first. `merge:` lines are `--no-ff` integration points.

```
f4c79b2  fix(admin): show the cadence that actually runs, and keep fit results (ALP-158)
b5af3d4  merge: ALP-155 honest Sortformer benchmark
  873569e / 7847ccb / 4258942 / 0a1c6e4 / 999729e   (ALP-155 train)
9782560  chore: refresh Sentrux structural baseline
df9fc5c  fix(llm): size request limits for self-hosted models (ALP-154)
501809f  fix(audio): bound the diarization backlog so a slow diarizer degrades, not dies (ALP-153)
a464751  merge: ALP-152 Privacy First admits self-hosted models
  2dec232 / d88c2de / 8ac935c                        (ALP-152 train)
5a058bd  merge: ALP-150 desktop updater
  4d7302a … 1663863                                  (ALP-150 train, 14 commits)
```

---

## 3. Branches and worktrees

| Branch | SHA | Worktree | State |
| --- | --- | --- | --- |
| `master` | `f4c79b2` | main checkout | 29 ahead of origin |
| `agent/alp-152-privacy-first-admits-self-hosted` | `2dec232` | — | **pushed**, PR #27 open |
| `agent/alp-129-quota-local-fallback` | `85b684b` | `C:/work/backchannel/alp-129` | local only; PR was closed |
| `agent/alp-155-benchmark-honesty` | `873569e` | `C:/work/backchannel/alp-155` | merged into master |
| `agent/alp-156-aggregate-resource-budget` | `94aea61` | `C:/work/backchannel/alp-156` | local only, **in progress** |
| `talberthoule/alp-150-updater` | `4d7302a` | `%TEMP%/backchannel-alp-150` | merged into master |

Worktrees live **outside** the checkout on purpose: OneDrive sync strips `.git` files
from worktrees created inside it (ALP-139). Two empty admin dirs
(`.git/worktrees/a155fix`, `.git/worktrees/alp155`) resist deletion because OneDrive
holds handles; `git worktree list` is consistent, so they are cosmetic. Run
`git worktree prune` later.

---

## 4. Lane status (polled by pane read, 2026-07-27 ~20:00Z)

Herdr `agent send` was **broken** for the last several hours — the plugin moved from
`herdr/coordinating-herdr-agents` to `shepherd/herdr-shepherd` and the new binary
returns `BrokenPipe`. **`herdr pane read` still works** and is the reliable pull
channel. ALP-161 (filed by another lane) tracks the audit trail silently missing sends.

| Pane | Lane | Issue | State |
| --- | --- | --- | --- |
| `w2:pJ` | claude | ALP-152/153/154/158 | all committed to master; this handoff |
| `w2:pB` | claude-seo (**Fable 5**) | ALP-156 | planner + admission **committed at `94aea61`**, unit-tested. Only a live integration test remains. Parked, awaiting a decision: stand up a read-only backend on `:8000`, or take the shared checkout. |
| `w2:pG` | claude-2 | ALP-129 | committed `85b684b` locally. Waiting for ALP-152 to land on origin so it can re-cut a clean single-commit PR based on it. |
| `w2:pH` | codex | ALP-155 | done and merged. Composer holds stale pasted content. |
| `w2:pK` | claude-comparison-1 | ALP-157 | reviewed ALP-155 and merge-coordinated; ALP-157 progress **unconfirmed**. |
| `w2:pE` | codex-app-layout | — | **pane no longer exists** |

Coordination convention in force: substance goes in Linear (`ALP-NNN`), Herdr sends
are pointers only. Lanes work in worktrees; only `w2:pJ` touched the shared checkout.

---

## 5. What was fixed today, and what it proved

All five landed on local `master` and were verified against a **real** LM Studio
endpoint and a live call, not only in tests.

- **ALP-152** — Privacy First judged models by provider name, so every text agent was
  silently dropped and the briefing returned 409. `provider_for(model) == "local"` can
  never be true for a text agent: endpoint models resolve to the OpenAI-compatible
  dialect, and all three `provider: "Local"` registry entries are ASR-only. Admission
  now resolves once per call via `privacy.admitted_model_ids`.
- **ALP-153** — the diarization queue was an unbounded `asyncio.Queue`; a Sortformer
  dual-track call grew it 2 → 1602 in 95s and the container was **OOM-killed**. Now
  capped at 30s of dual-track PCM, shedding oldest-first.
- **ALP-154** — 120s timeout and no `max_tokens` broke self-hosted briefings. Now 900s
  for self-hosted, an explicit budget that halves on a context refusal, and
  `finish_reason: length` reported as a named error.
- **ALP-155** (codex) — the benchmark's boolean unlock replaced by measured headroom.
- **ALP-158** — fit-test budgets write `model_intervals`, which the UI never read, and
  fit results were never persisted. Both fixed.

**Verified live on the final call** (Privacy First on, self-hosted qwen): 51 transcript
entries, **7 insights** (3 analyst lenses, 4 synthesizer), strategic signals firing,
briefing completing, and ALP-153 shedding 23 frames then **recovering to backlog=2**
instead of dying. That closes ALP-152 acceptance 2, the last unproven item.

### Two corrections the next operator should inherit

1. **Sortformer is not too slow.** I told the operator to switch away from it. The
   honest benchmark then measured **27.3× realtime, 810% headroom**. The OOM was real,
   but the cause was almost certainly memory footprint (one NeMo instance per track)
   and contention with `local-parakeet-live`, not throughput.
2. **ALP-164 is intermittent, not total.** The analyst does produce insights on some
   cycles; it silently discards others. See the correction comment on that issue.

---

## 6. Open work, highest value first

| Issue | Pri | Owner | Summary |
| --- | --- | --- | --- |
| **ALP-166** | Urgent | unassigned | Endpoint edits in Connections orphan every agent, budget, and fit result. **Live right now**: agents point at `endpoint:qwen3-5-4b:qwen3.5-4b`, which no longer exists — `resolve_endpoint` raises `EndpointUnavailable`. Repointing agents to `qwen3-5-4b-2` is the immediate workaround. |
| **ALP-165** | Urgent | unassigned | The app cannot tell a user why nothing is happening. Every failure today presented as silence. |
| **ALP-164** | Urgent | unassigned | Text agents use `generate_text` with no schema, so a local model's output is intermittently discarded. Fix: route through `generate_json` like `strategic_signals`. `outlines`/`instructor` were considered and rejected — reasons in the issue. |
| **ALP-156** | Urgent | Fable 5 (`w2:pB`) | Aggregate resource budget. Design agreed; planner committed at `94aea61`; needs live integration test. |
| **ALP-157** | High | `w2:pK` (unconfirmed) | Four features hardcode `settings.REFINEMENT_MODEL`, unusable under Privacy First. |
| **ALP-160** | Medium | unassigned | Persisted fit results have no staleness handling. ALP-166 is its live instance. |
| **ALP-129** | — | claude-2 (`w2:pG`) | Quota→self-hosted fallback, committed at `85b684b`, blocked on ALP-152 landing. |
| **ALP-150** | High | codex | Desktop updater, merged locally, **held from publish** behind the macOS signing gate. |
| **ALP-161** | — | other lane | Coordination audit trail silently missed sends. |

---

## 7. Bringing this up on the second machine

Local `master` is not on origin, so choose one:

**A. Push the branches** (operator decision; the repo is public):
```bash
git push origin master                                   # publishes ALP-150 too — see §1
git push origin agent/alp-156-aggregate-resource-budget
git push origin agent/alp-129-quota-local-fallback
```

**B. Transfer a bundle** without publishing anything:
```bash
git bundle create backchannel-handoff.bundle --all
# on the receiving machine:
git clone backchannel-handoff.bundle backchannel && cd backchannel
```

Option B is the safer default while ALP-150's gate is open.

### Environment the work assumes

- Stack: `docker-compose up --build -d`; frontend `:3000`, backend `:8001`, Postgres `:5432`.
- **`./backend/app` is bind-mounted into the backend container**, so it serves the
  working tree live and a branch switch changes running code. The **frontend is
  image-baked** and needs a rebuild. This tripped one lane already.
- Tests: `cd backend && python -m unittest discover -s tests` — **668 pass**, with one
  known Windows-only failure (`test_secrets.test_master_key_file_created_private`,
  POSIX `0o600` chmod). Not a regression.
- Use the repo-root `.release-venv` (or `%LOCALAPPDATA%\Programs\Python\Python312`);
  `python` on PATH may be a Store stub.
- Sentrux: `sentrux check .` — clean at quality **6485**, only the two approved
  lockfile exceptions.
- Local models: LM Studio on `host.docker.internal:1234`. qwen3.5-4b now runs at
  **256k context** (was ~8k, which was what blocked the briefing).

### Do not repeat these

- Check `git log origin/master..HEAD` before any push.
- Do not merge to `master` or push without the operator; they hold that decision.
- Linear issue bodies must be **plain prose** — fenced code blocks and markdown tables
  trip the Cloudflare WAF and the write is rejected.
- Only one lane should hold the shared checkout at a time.
