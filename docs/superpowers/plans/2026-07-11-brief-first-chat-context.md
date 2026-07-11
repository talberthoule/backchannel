# Brief-First Meeting Chat Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make meeting chat use each selected session's settled briefing, saved insights, and transcript, with the briefing guiding interpretation and the transcript grounding facts and quotations.

**Architecture:** The existing `/api/chat` route loads two additional persisted models and formats them as compact JSON context. `build_chat_prompt` admits briefing blocks first, insight blocks second, and transcript blocks last within the existing 60,000-character budget; the system instruction defines the evidence and conflict contract. The frontend request shape remains unchanged.

**Tech Stack:** FastAPI, SQLAlchemy 2 async ORM, Python stdlib `json`, Pydantic 2, stdlib `unittest`, React/TypeScript, existing provider-routed LLM service.

## Global Constraints

- Include only `completed` or `partial` post-call syntheses as settled briefings.
- Include every non-dismissed saved insight for each selected meeting before budget truncation.
- Use briefing for priorities/themes, insights for supporting analysis, and transcript for factual grounding/direct quotes.
- Surface source conflicts; never silently replace direct transcript evidence with synthesis text.
- Preserve the 60,000-character meeting-context budget and eight-message chat-history limit.
- Bound selected sessions to 20 at the request boundary.
- Under truncation, admit briefings before insights and insights before transcripts; newest sessions survive first and rendered sessions remain chronological.
- Add no model call, embedding service, vector store, schema migration, endpoint, or dependency.

---

## File Map

- Modify `backend/tests/test_chat_prompt.py`: layered prompt and formatter regression tests.
- Modify `backend/app/routers/chat.py`: model queries, compact formatting, priority budget, and system contract.
- Modify `frontend/src/components/PostCall/MeetingChat.tsx`: accurate context labels and empty-state copy.
- Modify `docs/rest-api.md`: document the `/api/chat` context and precedence.
- Modify `README.md`: describe cross-session Q&A over briefings, insights, and transcripts.

### Task 1: Priority-aware prompt assembly

**Files:**
- Modify: `backend/tests/test_chat_prompt.py`
- Modify: `backend/app/routers/chat.py:18-65`

**Interfaces:**
- Consumes: session dictionaries with `briefing: str`, `insights: str`, and `lines: list[tuple[str, str]]`.
- Produces: `build_chat_prompt(sessions_data, messages, budget) -> str` with three ordered context layers.

- [ ] **Step 1: Extend the test helper and add failing priority tests**

Change the helper in `backend/tests/test_chat_prompt.py` to:

```python
def session_data(name, lines, *, briefing="", insights="", started_at="2026-07-01"):
    return {
        "name": name,
        "started_at": started_at,
        "sort_key": started_at,
        "briefing": briefing,
        "insights": insights,
        "lines": lines,
    }
```

Add these tests:

```python
    def test_briefing_insights_and_transcript_are_layered_in_priority_order(self):
        sessions = [session_data(
            "Discovery",
            [("Alice", "Transcript evidence")],
            briefing='{"top_outcomes":[{"title":"Primary outcome"}]}',
            insights='[{"text":"Supporting insight"}]',
        )]
        prompt = build_chat_prompt(sessions, [{"role": "user", "content": "What matters?"}], budget=10000)

        self.assertIn("# Meeting Briefings (primary context)", prompt)
        self.assertIn("# Saved Insights (supporting context)", prompt)
        self.assertIn("# Meeting Transcripts (grounding evidence)", prompt)
        self.assertLess(prompt.index("Primary outcome"), prompt.index("Supporting insight"))
        self.assertLess(prompt.index("Supporting insight"), prompt.index("Transcript evidence"))

    def test_budget_truncates_transcript_after_preserving_brief_and_insight(self):
        sessions = [session_data(
            "Discovery",
            [("Alice", "T" * 5000)],
            briefing="BRIEFING_PRIORITY",
            insights="INSIGHT_PRIORITY",
        )]
        prompt = build_chat_prompt(sessions, [{"role": "user", "content": "q"}], budget=600)

        self.assertIn("BRIEFING_PRIORITY", prompt)
        self.assertIn("INSIGHT_PRIORITY", prompt)
        self.assertIn("[truncated]", prompt)
        self.assertNotIn("T" * 5000, prompt)

    def test_missing_optional_layers_still_allows_transcript_chat(self):
        sessions = [session_data("Transcript only", [("Bob", "Ground truth")])]
        prompt = build_chat_prompt(sessions, [{"role": "user", "content": "q"}], budget=10000)

        self.assertNotIn("Meeting Briefings", prompt)
        self.assertNotIn("Saved Insights", prompt)
        self.assertIn("Ground truth", prompt)

    def test_newest_session_survives_layer_truncation(self):
        old = session_data("Old", [], briefing="O" * 5000, started_at="2026-07-01")
        new = session_data("New", [], briefing="NEW_BRIEF", started_at="2026-07-02")
        prompt = build_chat_prompt([old, new], [{"role": "user", "content": "q"}], budget=500)

        self.assertIn("NEW_BRIEF", prompt)
        self.assertIn("[truncated]", prompt)
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run from the repository root using the known backend image:

```powershell
$backend = (Resolve-Path 'backend').Path
$frontend = (Resolve-Path 'frontend').Path
docker run --rm --mount "type=bind,source=$backend,target=/app" --mount "type=bind,source=$frontend,target=/frontend" -w /app backchannel-backend:latest python -m unittest tests.test_chat_prompt -v
```

Expected: new tests FAIL because the prompt contains transcripts only.

- [ ] **Step 3: Implement one reusable layer-budget helper and update the prompt**

Replace `SYSTEM_PROMPT` and `build_chat_prompt` in `backend/app/routers/chat.py` with:

```python
SYSTEM_PROMPT = (
    "You are a meeting analysis assistant. Use ONLY the supplied meeting "
    "briefings, saved insights, transcripts, and chat history. Begin from the "
    "briefing when deciding priorities, themes, outcomes, risks, and next steps. "
    "Use saved insights for supporting analysis and unresolved detail. Use the "
    "transcript as factual grounding and the only source for direct quotations. "
    "If sources conflict, identify the conflict and ground factual claims in the "
    "transcript. If the supplied context does not contain the answer, say so "
    "plainly. Format the response as concise GitHub-flavored Markdown with short "
    "headings, bullets, and tables only when they improve readability."
)


def _layer_blocks(sessions_data: list[dict], key: str, remaining: int) -> tuple[str, int]:
    blocks: list[str] = []
    for data in reversed(sessions_data):
        if key == "transcript":
            content = "\n".join(f"{speaker}: {text}" for speaker, text in data["lines"])
        else:
            content = data.get(key, "").strip()
        if not content:
            continue

        block = f"## {data['name']} ({data['started_at']})\n{content}"
        if len(block) > remaining:
            marker = "\n[truncated]"
            keep = remaining - len(marker)
            block = (block[:keep] + marker) if keep > 100 else ""
        if block:
            blocks.insert(0, block)
            remaining -= len(block)
        if remaining <= 0:
            break
    return "\n\n".join(blocks), remaining


def build_chat_prompt(sessions_data: list[dict], messages: list[dict], budget: int = CONTEXT_BUDGET_CHARS) -> str:
    """Assemble brief-first meeting context plus bounded conversation history."""
    messages = messages[-MAX_CHAT_HISTORY_MESSAGES:]
    remaining = budget
    sections: list[str] = []
    for heading, key in (
        ("Meeting Briefings (primary context)", "briefing"),
        ("Saved Insights (supporting context)", "insights"),
        ("Meeting Transcripts (grounding evidence)", "transcript"),
    ):
        content, remaining = _layer_blocks(sessions_data, key, remaining)
        if content:
            sections.append(f"# {heading}\n\n{content}")
        if remaining <= 0:
            break

    conversation = "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in messages)
    sections.append(f"# Conversation\n{conversation}\nAssistant:")
    return "\n\n".join(sections)
```

- [ ] **Step 4: Run the focused tests and verify pass**

Repeat the Docker `python -m unittest tests.test_chat_prompt -v` command.

Expected: all chat-prompt tests PASS.

- [ ] **Step 5: Commit prompt priority**

```bash
git add backend/app/routers/chat.py backend/tests/test_chat_prompt.py
git commit -m "feat: prioritize briefings in meeting chat"
```

### Task 2: Load and format persisted briefings and insights

**Files:**
- Modify: `backend/tests/test_chat_prompt.py`
- Modify: `backend/app/routers/chat.py:1-14,28-40,69-106`

**Interfaces:**
- Consumes: `SessionSynthesis`, its `clusters`, non-dismissed `Question` rows, and existing speaker names.
- Produces: `_format_briefing(synthesis) -> str` and `_format_insights(items, speaker_names) -> str` compact JSON blocks.

- [ ] **Step 1: Add failing formatter and request-bound tests**

Add imports to `backend/tests/test_chat_prompt.py`:

```python
from types import SimpleNamespace

from pydantic import ValidationError

from app.routers.chat import ChatIn, _format_briefing, _format_insights, build_chat_prompt
```

Replace its existing `build_chat_prompt` import and add:

```python
    def test_briefing_formatter_keeps_settled_sections_clusters_and_notes(self):
        synthesis = SimpleNamespace(
            status="completed",
            top_outcomes=[{"title": "Outcome", "summary": "Confirmed"}],
            client_objectives=[],
            top_opportunities=[],
            risks_blockers=[],
            action_plan=[{"title": "Send proposal", "owner": "Alice"}],
            unresolved_discovery_questions=[],
            strategic_signals=[],
            arbiter_notes="Brief wins on priorities.",
            clusters=[SimpleNamespace(
                title="Security",
                summary="SSO and audit requirements",
                priority=1,
                confidence="high",
            )],
        )

        content = _format_briefing(synthesis)
        self.assertIn('"Outcome"', content)
        self.assertIn('"Send proposal"', content)
        self.assertIn('"Security"', content)
        self.assertIn('"Brief wins on priorities."', content)

    def test_briefing_formatter_omits_unsettled_synthesis(self):
        self.assertEqual("", _format_briefing(SimpleNamespace(status="pending")))
        self.assertEqual("", _format_briefing(SimpleNamespace(status="error")))

    def test_insight_formatter_keeps_active_detail_and_speaker(self):
        item = SimpleNamespace(
            id="insight-1",
            item_type="action_item",
            question="Send the proposal.",
            rationale="Customer requested Friday.",
            source_context="Alice committed on the call.",
            speaker_id="speaker-1",
            answered=True,
            answer_summary="Friday confirmed.",
            needs_followup=False,
            followup_question="",
            offering_match="",
        )
        content = _format_insights([item], {"speaker-1": "Alice"})
        self.assertIn('"speaker":"Alice"', content)
        self.assertIn('"answer_summary":"Friday confirmed."', content)
        self.assertIn('"source_context":"Alice committed on the call."', content)

    def test_chat_request_rejects_more_than_twenty_sessions(self):
        with self.assertRaises(ValidationError):
            ChatIn(
                model_id="gemini-test",
                session_ids=[f"00000000-0000-0000-0000-{index:012d}" for index in range(21)],
                messages=[{"role": "user", "content": "q"}],
            )
```

- [ ] **Step 2: Run focused tests and verify failure**

Run the Docker chat-test command from Task 1.

Expected: FAIL because `_format_briefing`, `_format_insights`, and the 20-session bound do not exist.

- [ ] **Step 3: Add compact stdlib JSON formatters and input bound**

In `backend/app/routers/chat.py`:

```python
import json
```

Extend model/ORM imports:

```python
from sqlalchemy.orm import selectinload

from app.models import Question, Session, SessionSynthesis, Speaker, TranscriptEntry
```

Change `ChatIn.session_ids` to:

```python
    session_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
```

Add:

```python
BRIEFING_FIELDS = (
    "top_outcomes",
    "client_objectives",
    "top_opportunities",
    "risks_blockers",
    "action_plan",
    "unresolved_discovery_questions",
    "strategic_signals",
)


def _format_briefing(synthesis) -> str:
    if synthesis is None or getattr(synthesis, "status", "") not in {"completed", "partial"}:
        return ""
    content = {field: getattr(synthesis, field, []) or [] for field in BRIEFING_FIELDS}
    content["insight_clusters"] = [
        {
            "title": cluster.title,
            "summary": cluster.summary,
            "priority": cluster.priority,
            "confidence": cluster.confidence,
        }
        for cluster in (getattr(synthesis, "clusters", []) or [])
    ]
    content["arbiter_notes"] = getattr(synthesis, "arbiter_notes", "") or ""
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))


def _format_insights(items, speaker_names: dict[str, str]) -> str:
    if not items:
        return ""
    content = [
        {
            "id": str(item.id),
            "type": item.item_type,
            "text": item.question,
            "rationale": item.rationale,
            "source_context": item.source_context,
            "speaker": speaker_names.get(str(item.speaker_id), "Unknown") if item.speaker_id else "",
            "answered": item.answered,
            "answer_summary": item.answer_summary,
            "needs_followup": item.needs_followup,
            "followup_question": item.followup_question,
            "offering_match": item.offering_match,
        }
        for item in items
    ]
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))
```

- [ ] **Step 4: Load the persisted context in the existing session loop**

After the transcript query in `chat`, add:

```python
        synthesis_result = await db.execute(
            select(SessionSynthesis)
            .where(
                SessionSynthesis.session_id == session_id,
                SessionSynthesis.mode == "post_call",
                SessionSynthesis.status.in_(("completed", "partial")),
            )
            .options(selectinload(SessionSynthesis.clusters))
        )
        synthesis = synthesis_result.scalar_one_or_none()

        insights_result = await db.execute(
            select(Question)
            .where(Question.session_id == session_id, Question.dismissed.is_(False))
            .order_by(Question.created_at)
        )
        insights = insights_result.scalars().all()
```

Build each session dictionary with:

```python
        started = session.started_at or session.created_at
        sessions_data.append({
            "name": session.name,
            "started_at": started.date().isoformat() if started else "unknown date",
            "sort_key": started.isoformat() if started else "",
            "briefing": _format_briefing(synthesis),
            "insights": _format_insights(insights, speaker_names),
            "lines": lines,
        })
```

Immediately after the loop add:

```python
    sessions_data.sort(key=lambda data: data["sort_key"])
```

Delete the now-redundant explicit `if not body.session_ids` and `if not body.messages` checks because Pydantic enforces both bounds before the route executes.

- [ ] **Step 5: Run focused tests and verify pass**

Run the Docker chat-test command.

Expected: all chat-prompt tests PASS.

- [ ] **Step 6: Run the full backend suite**

```powershell
$backend = (Resolve-Path 'backend').Path
$frontend = (Resolve-Path 'frontend').Path
docker run --rm --mount "type=bind,source=$backend,target=/app" --mount "type=bind,source=$frontend,target=/frontend" -w /app backchannel-backend:latest python -m unittest discover -s tests
```

Expected: 188 tests PASS, 0 failures.

- [ ] **Step 7: Commit persisted context loading**

```bash
git add backend/app/routers/chat.py backend/tests/test_chat_prompt.py
git commit -m "feat: include briefs and insights in meeting chat"
```

### Task 3: Accurate UI and API documentation

**Files:**
- Modify: `frontend/src/components/PostCall/MeetingChat.tsx:138-224`
- Modify: `docs/rest-api.md:174-179`
- Modify: `README.md:48-49`

**Interfaces:**
- Consumes: unchanged `/api/chat` request/response shape.
- Produces: UI and documentation that accurately disclose all three context layers.

- [ ] **Step 1: Update the visible chat copy**

In `MeetingChat.tsx`, replace:

```tsx
<span className="font-body text-xs font-medium text-brand-gray">Transcripts:</span>
```

with:

```tsx
<span className="font-body text-xs font-medium text-brand-gray">Meetings:</span>
```

Replace the empty-state sentence with:

```tsx
Ask across the selected meetings&apos; briefing, saved insights, and transcript.
```

No component structure, request payload, selector behavior, or styling changes.

- [ ] **Step 2: Update durable documentation**

Change the `/api/chat` row in `docs/rest-api.md` to:

```markdown
| POST | `/api/chat` | Ask questions over selected sessions' settled briefings, non-dismissed insights, and speaker-attributed transcripts; briefings guide interpretation while transcripts ground facts and quotations |
```

Change the README feature to:

```markdown
- **Exports and chat** -- transcript TXT, insights XLSX, and summary HTML
  exports, plus cross-session Q&A grounded in each meeting's briefing,
  saved insights, and speaker-attributed transcript
```

- [ ] **Step 3: Build the frontend and docs site**

```bash
cd frontend && npm run build
cd ../docs-site && npm run build
```

Expected: TypeScript/Vite build PASS and Astro/site assembly PASS.

- [ ] **Step 4: Commit UI and docs**

```bash
git add frontend/src/components/PostCall/MeetingChat.tsx docs/rest-api.md README.md
git commit -m "docs: describe brief-first meeting chat"
```

### Task 4: Behavioral verification

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: a completed meeting with briefing, insights, and transcript plus a configured text model.
- Produces: evidence that production-shaped chat uses all sources with the intended precedence.

- [ ] **Step 1: Run all automated checks**

Run the full backend suite, `frontend/npm run build`, `docs-site/npm run build`,
`docker compose config --quiet`, `docker compose build frontend backend`, and
`git diff --check`.

Expected: all checks PASS; only the existing Vite chunk-size advisory may appear.

- [ ] **Step 2: Inspect one generated prompt without sending private meeting data externally**

Use synthetic session dictionaries and `build_chat_prompt` inside the backend container. Verify the output includes all three section headings, briefing before insights before transcript, and a truncated transcript under a constrained budget. Do not print real transcripts, briefs, or emails.

- [ ] **Step 3: Verify the local UI copy**

Open the existing local Backchannel frontend in the browser, enter a completed session's Chat tab, and confirm `Meetings:` plus the three-layer empty-state copy render correctly at desktop and mobile widths. Do not submit a real meeting chat solely for smoke testing.

- [ ] **Step 4: Verify post-merge behavior with synthetic content**

After deployment of a version containing the backend change, use a disposable synthetic session whose briefing, insight, and transcript contain distinct markers. Ask one question and confirm the response reflects the briefing's priority, preserves the insight detail, grounds quotations in the transcript, and calls out a deliberately introduced conflict.
