# ALP-140 Demo Data and Showcase Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Northwind demo with a deterministic Alderwake Health Network recovery-readiness story and regenerate every public showcase asset from the real product UI.

**Architecture:** Keep `showcase/seed_demo.py` as the single fixture source, make `showcase/capture.mjs` cover all twelve surfaces, and retain the existing Pillow encode/crop pipeline. Add one unittest manifest check so stale story text, missing themes, and wrong dimensions fail locally before site publication.

**Tech Stack:** Python 3.12 stdlib + Pillow, PostgreSQL through the existing Docker Compose database, Playwright from the installed product-showcase kit, React/Vite, Astro/Starlight, Cloudflare Wrangler via GitHub Actions.

## Global Constraints

- All companies, people, numbers, notes, and quotes are fictional.
- Committed screenshots use deterministic canned data and never require an LLM key.
- Screenshots come from the real product UI; do not generatively edit them.
- Capture all twelve surfaces in light and dark themes and all three derived crops in both themes.
- Preserve the existing teal visual system and homepage structure; this is a content and asset replacement, not a redesign.
- Keep new source text ASCII unless the surrounding file already requires non-ASCII punctuation.
- Do not touch or publish the retired `showcase/archive/2026-07-24-retired-user-assets/` family.
- `claude-2` (`w2:pG`) must return a clear editorial verdict before merge, push, or deployment.

---

### Task 1: Add the deterministic showcase contract

**Files:**
- Create: `showcase/test_showcase_assets.py`

**Interfaces:**
- Consumes: `showcase.seed_demo`, tracked screenshot PNGs, and `site/assets/shots/*.webp`.
- Produces: `python -m unittest showcase.test_showcase_assets`, the single runnable showcase contract used by later tasks.

- [ ] **Step 1: Write the failing fixture and asset tests**

```python
FULL = {
    "live-call": (1440, 900),
    "postcall-briefing": (1440, 900),
    "postcall-insights": (1440, 900),
    "postcall-transcript": (1440, 900),
    "postcall-speakers": (1440, 900),
    "postcall-chat": (1440, 900),
    "admin-agents": (1185, 900),
    "admin-transcription": (1185, 900),
    "admin-api-keys": (1185, 900),
    "admin-about": (1185, 900),
    "offerings-catalog": (1185, 900),
    "knowledge-sources": (1185, 900),
}
CROPS = {
    "live-answered": (732, 508),
    "insights-attributed": (1032, 460),
    "session-header": (1032, 166),
}

def test_fixture_identity(self):
    self.assertEqual("Alderwake Health Network", seed_demo.GROUP)
    self.assertIn("recovery readiness review", seed_demo.MAIN)
    self.assertEqual(24, len(seed_demo.INSIGHTS))

def test_retired_story_is_absent_from_current_sources(self):
    for path in CURRENT_SOURCE_PATHS:
        text = path.read_text(encoding="utf8")
        for marker in ("Northwind Logistics", "segmentation review", "cross-dock"):
            self.assertNotIn(marker, text, path)
```

- [ ] **Step 2: Run the check and verify it fails on the current fixture**

Run: `.\.venv\Scripts\python.exe -m unittest showcase.test_showcase_assets -v`

Expected: FAIL because `seed_demo.GROUP` is still `Northwind Logistics` and current sources contain retired markers.

- [ ] **Step 3: Commit the failing contract**

```powershell
git add showcase/test_showcase_assets.py
git commit -m "test(showcase): define deterministic asset contract"
```

---

### Task 2: Replace the fixture and seed the missing product data

**Files:**
- Modify: `showcase/seed_demo.py`
- Modify: `backend/app/routers/offerings.py`
- Test: `showcase/test_showcase_assets.py`

**Interfaces:**
- Consumes: existing REST APIs for sessions, speakers, transcripts, offerings, knowledge sources, and records; existing `psql()` helper for insights and synthesis rows.
- Produces: `GROUP`, `MAIN`, `SPEAKERS`, `LINES`, `INSIGHTS`, `OTHERS`, `BRIEFING`, and `KNOWLEDGE_RECORDS`; an idempotent `seed_demo.py --reset` run with exactly 24 canned insights and a completed briefing.

- [ ] **Step 1: Replace the session story**

Set:

```python
GROUP = "Alderwake Health Network"
MAIN = "Alderwake Health Network - recovery readiness review"
```

Use four speakers: `Me` (Account Lead), `Leah` (Solutions Architect), `Owen` (Director of Infrastructure), and `Maya` (Security Lead). Rewrite the full transcript around an eight-hour recovery gap, a board risk deadline, a non-disruptive pilot, procurement boundaries, managed operations, recovery ownership, and a Thursday follow-up.

- [ ] **Step 2: Replace canned insights with the exact 24-item mix**

Create 5 action items, 4 objections, 4 opportunities, 5 observations, and 6 questions. Keep each item grounded in an exact fictional transcript phrase and preserve answered/follow-up/offering-match coverage for the current UI states.

- [ ] **Step 3: Seed deterministic briefing JSON**

Add a `BRIEFING` dictionary with top outcomes, client objectives, opportunities, risks, action plan, and unresolved discovery questions. Insert one completed `session_syntheses` row after questions so the Briefing surface renders without calling an LLM.

```python
briefing_columns = (
    "id, session_id, mode, status, top_outcomes, client_objectives, "
    "top_opportunities, risks_blockers, action_plan, "
    "unresolved_discovery_questions, strategic_signals, evidence_refs, "
    "lens_meeting, lens_discovery, arbiter_notes, model_ids, error_message, "
    "created_at, updated_at"
)
```

- [ ] **Step 4: Populate Offerings and Knowledge Sources through real APIs**

Call `POST /offerings/seed?replace=true`. Delete only an existing source named `Recovery Delivery Playbooks`, recreate it as a `collection`, and add three records: `Recovery readiness pilot`, `Clinical change-window guardrails`, and `Managed recovery operations`.

- [ ] **Step 5: Tighten the generic sample catalog only where the scenario needs it**

Keep the installed-dependency-free `_get_seed_data()` list. Rename the in-house vendor label to `Service Integrator` and ensure the catalog includes `Recovery Readiness Assessment`, `Recovery Implementation Pilot`, and `Managed Recovery Operations` while retaining useful vendor-product examples.

- [ ] **Step 6: Run the source half of the contract**

Run: `.\.venv\Scripts\python.exe -m unittest showcase.test_showcase_assets.ShowcaseFixtureTests -v`

Expected: PASS for identity, counts, type mix, and retired-source scan. Asset checks may still fail until Task 4.

- [ ] **Step 7: Commit the fixture**

```powershell
git add showcase/seed_demo.py backend/app/routers/offerings.py showcase/test_showcase_assets.py
git commit -m "feat(showcase): seed recovery readiness demo"
```

---

### Task 3: Make every screenshot reproducible

**Files:**
- Modify: `showcase/capture.mjs`
- Modify: `showcase/screenshots/README.md`
- Test: `showcase/test_showcase_assets.py`

**Interfaces:**
- Consumes: the deterministic session, briefing, offerings, and knowledge collection from Task 2.
- Produces: twenty-four 1440x900 PNG captures, including chat and live call, with stable wait selectors and no LLM-key branch.

- [ ] **Step 1: Remove the credential-dependent capture branch**

Always wait for the seeded Briefing content and delete the credentials lookup and skip notices. Use `SESSION = "Alderwake Health Network - recov"`.

- [ ] **Step 2: Seed chat through the product's session-storage contract**

After the page has loaded the origin, set:

```javascript
sessionStorage.setItem(
  `backchannel:meeting-chat:${sessionId}`,
  JSON.stringify([
    { role: "user", content: "What did we commit to, and what could still move the recovery pilot?" },
    { role: "assistant", content: "**Committed:** ...\n\n**Could move the pilot:** ..." },
  ]),
);
```

Open the real Chat tab, wait for `Committed:`, and capture `postcall-chat`.

- [ ] **Step 3: Capture populated catalog and playbooks**

Wait for `Recovery Readiness Assessment` on Offerings Catalog. Open Knowledge Sources, select `Recovery Delivery Playbooks`, wait for `3 records`, and capture that selected collection.

- [ ] **Step 4: Add real Active Call capture in both themes**

After all completed-call surfaces are captured in both themes, PATCH the demo session to `active`, open it in a Playwright context launched with fake-media permission, select `Resume Audio`, wait for `Listening`, and capture `live-call`. Close the page, restore `completed`, and repeat for dark mode.

- [ ] **Step 5: Update the screenshot README**

Document the complete deterministic command sequence, all twelve surfaces, all three crops, the 24-insight counts, and that chat/briefing are fixture-backed rather than key-dependent.

- [ ] **Step 6: Run syntax and static capture checks**

Run:

```powershell
node --check showcase/capture.mjs
.\.venv\Scripts\python.exe -m unittest showcase.test_showcase_assets.ShowcaseFixtureTests -v
```

Expected: both PASS.

- [ ] **Step 7: Commit capture automation**

```powershell
git add showcase/capture.mjs showcase/screenshots/README.md showcase/test_showcase_assets.py
git commit -m "feat(showcase): capture every demo surface"
```

---

### Task 4: Regenerate assets and align public copy

**Files:**
- Modify: `showcase/screenshots/*.png`
- Modify: `site/assets/shots/*.webp`
- Modify: `showcase/crops.py` only if visual inspection requires new crop boxes
- Modify: `site/index.html`
- Modify: `docs/agents.md`
- Modify: `docs/api-keys.md`
- Modify: `docs/configuration.md`
- Test: `showcase/test_showcase_assets.py`

**Interfaces:**
- Consumes: the complete capture pipeline from Task 3.
- Produces: twenty-four source PNGs, thirty WebP assets, accurate homepage counts/captions/alt text/dimensions, and passing asset manifest checks.

- [ ] **Step 1: Rebuild and seed the local app**

Run the existing Compose stack against this worktree with the user's existing external `.env`, then:

```powershell
.\.venv\Scripts\python.exe showcase\seed_demo.py --reset
node showcase\capture.mjs
.\.venv\Scripts\python.exe showcase\encode.py
.\.venv\Scripts\python.exe showcase\crops.py
```

- [ ] **Step 2: Run the asset contract**

Run: `.\.venv\Scripts\python.exe -m unittest showcase.test_showcase_assets -v`

Expected: all fixture, source, filename, theme, and dimension checks PASS.

- [ ] **Step 3: Visually inspect the complete set**

Inspect light/dark representatives for the hero, briefing, insights, transcript, chat, catalog, knowledge source, and every crop. If a crop clips its target, change only its tuple in `CROPS` and rerun `showcase/crops.py`.

- [ ] **Step 4: Replace exact public statistics and image metadata**

Change homepage references from 56 insights to 24, use the seeded type counts `5 / 4 / 4 / 5 / 6`, retain the 46:12 duration, and update every image `width`, `height`, alt text, and figcaption to what the new captures actually show.

- [ ] **Step 5: Build and inspect the assembled site**

Run `npm run build` from `docs-site`, serve `dist-site` locally, and inspect the homepage at 1440px and 320px without horizontal overflow or stale imagery.

- [ ] **Step 6: Commit code, copy, and binaries together**

```powershell
git add showcase site docs
git commit -m "feat(site): publish the Alderwake showcase"
```

---

### Task 5: Editorial gate, verification, and production release

**Files:**
- Modify: only files required by actionable `claude-2` findings.
- Update: Linear issue `ALP-140`.

**Interfaces:**
- Consumes: complete branch diff, homepage copy, screenshot manifest, and representative captures.
- Produces: a clear `claude-2` editorial verdict, reviewed merged commit, successful Cloudflare workflow, and verified production pages/assets.

- [ ] **Step 1: Send the review package to `claude-2`**

Use the audited Herdr coordination wrapper with `origin: user-directed`. Include the branch name and committed SHA; point to a tracked review packet containing the diff summary, homepage copy, screenshot manifest, and local capture paths. Verify delivery by pane read.

- [ ] **Step 2: Implement actionable editorial findings**

Apply the smallest changes that improve clarity, consistency, and scenario credibility. Record rejected suggestions with concrete reasons only when they conflict with truth, privacy, accessibility, or the approved scope.

- [ ] **Step 3: Run the complete verification gate**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest showcase.test_showcase_assets -v
cd frontend; npm run build
cd ..\backend; ..\.venv\Scripts\python.exe -m unittest discover -s tests
cd ..\docs-site
npm run test:release-access
npm run test:migration
npm run test:worker
npm run test:admin
npm run test:download
npm run test:site
node --test *.test.js
npm run build
cd ..
sentrux check .
sentrux gate .
git diff --check
```

Accept only the already-reproduced Windows chmod baseline failure in `test_master_key_file_created_private`; no new failure is allowed.

- [ ] **Step 4: Push and merge**

Push `talberthoule/alp-140-demo-assets`, open a PR referencing ALP-140, confirm checks, merge to `master`, and verify `origin/master` contains the reviewed commit.

- [ ] **Step 5: Verify Cloudflare production**

Wait for `.github/workflows/deploy-site.yml` on the merged SHA. Verify `https://backchannel.page/` contains the new 24-insight copy and fetch representative new light/dark assets with HTTP 200 responses.

- [ ] **Step 6: Close Linear**

Comment with the merge SHA, Cloudflare workflow result, production verification, test totals, and the `claude-2` verdict; then set ALP-140 to Done.
