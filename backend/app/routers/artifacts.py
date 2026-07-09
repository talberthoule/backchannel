import os
import tempfile
import uuid
from datetime import datetime, timezone
from html import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Session, Question, Speaker, TranscriptEntry, SessionSynthesis
from sqlalchemy import select
from sqlalchemy.orm import selectinload

router = APIRouter(prefix="/api/sessions/{session_id}/artifacts", tags=["artifacts"])


async def _stream_and_cleanup(file_path: str, media_type: str, filename: str):
    """Stream a temp file to the client, then delete it immediately after."""
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk
    finally:
        try:
            os.unlink(file_path)
        except OSError:
            pass


def _stream_bytes(data: bytes):
    """Stream in-memory bytes — nothing ever touches disk."""
    yield data


@router.get("/transcript-export")
async def export_transcript(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Export session transcript as a downloadable text file. Generated in-memory, never stored."""
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    result = await db.execute(
        select(TranscriptEntry)
        .where(TranscriptEntry.session_id == session_id)
        .order_by(TranscriptEntry.sequence)
    )
    entries = result.scalars().all()

    # Load speakers for display name substitution
    spk_result = await db.execute(
        select(Speaker).where(Speaker.session_id == session_id)
    )
    speakers = spk_result.scalars().all()
    speaker_name_map = {}
    for s in speakers:
        if s.display_name and s.display_name_enabled:
            speaker_name_map[s.name] = s.display_name

    def _apply_names(text: str) -> str:
        for original, display in speaker_name_map.items():
            text = text.replace(original, display)
        return text

    lines = [f"Transcript: {session.name}", f"Date: {session.started_at or session.created_at}", ""]
    for entry in entries:
        ts = entry.timestamp.strftime("%H:%M:%S") if entry.timestamp else ""
        lines.append(f"[{ts}] {_apply_names(entry.text)}")

    content = "\n".join(lines).encode("utf-8")
    filename = f"transcript-{session.name.replace(' ', '_')}.txt"

    return StreamingResponse(
        _stream_bytes(content),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/questions-export")
async def export_insights(
    session_id: uuid.UUID,
    enhanced_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Export session insights as a formatted Excel (.xlsx) file."""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.worksheet.table import Table, TableStyleInfo
    from openpyxl.worksheet.filters import AutoFilter, CustomFilter, CustomFilters, FilterColumn
    from openpyxl.utils import get_column_letter

    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    result = await db.execute(
        select(Question)
        .where(Question.session_id == session_id)
        .order_by(Question.vote.desc(), Question.created_at)
    )
    questions = result.scalars().all()
    if enhanced_only:
        questions = [q for q in questions if q.enhanced]

    wb = Workbook()
    ws = wb.active
    ws.title = "Insights"

    # Load speakers for source_context name replacement
    spk_result = await db.execute(
        select(Speaker).where(Speaker.session_id == session_id)
    )
    speakers = spk_result.scalars().all()
    speaker_name_map = {}
    for s in speakers:
        if s.display_name and s.display_name_enabled:
            speaker_name_map[s.name] = s.display_name

    def _apply_speaker_names(text: str) -> str:
        for original, display in speaker_name_map.items():
            text = text.replace(original, display)
        return text

    headers = [
        "Type",
        "Lens",
        "Insight",
        "Rationale",
        "Source Context",
        "Vote",
        "Starred",
        "Answered",
        "Answer Summary",
        "Needs Follow-up",
        "Follow-up Question",
        "Offering Match",
        "Enhanced",
        "Dismissed",
        "Enrichment Notes",
        "Agent Source",
        "Revision Count",
        "Created At",
    ]
    ws.append(headers)

    type_labels = {
        "question": "Question",
        "observation": "Observation",
        "opportunity": "Opportunity",
        "action_item": "Action Item",
        "objection": "Objection",
    }

    for q in questions:
        ws.append([
            type_labels.get(q.item_type, (q.item_type or "question").replace("_", " ").title()),
            q.lens_label or "",
            _apply_speaker_names(q.question),
            _apply_speaker_names(q.rationale),
            _apply_speaker_names(q.source_context),
            q.vote or 0,
            q.starred,
            q.answered,
            _apply_speaker_names(q.answer_summary) if q.answer_summary else "",
            q.needs_followup,
            q.followup_question or "",
            q.offering_match or "",
            q.enhanced,
            q.dismissed,
            q.enrichment_notes or "",
            q.agent_source or "",
            q.revision_count,
            q.created_at.strftime("%Y-%m-%d %H:%M:%S") if q.created_at else "",
        ])

    # Format as an Excel Table
    if questions:
        last_col = get_column_letter(len(headers))
        last_row = len(questions) + 1
        table_ref = f"A1:{last_col}{last_row}"
        table = Table(displayName="Insights", ref=table_ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium9",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        # Default filter: Dismissed column (index 11) shows only FALSE
        dismissed_col_idx = headers.index("Dismissed")
        dismissed_filter = FilterColumn(
            colId=dismissed_col_idx,
            customFilters=CustomFilters(customFilter=[
                CustomFilter(val="FALSE"),  # openpyxl custom filter matches string repr
            ]),
        )
        table.autoFilter = AutoFilter(ref=table_ref)
        table.autoFilter.filterColumn.append(dismissed_filter)

        # Hide dismissed rows so the filter appears pre-applied when opened
        for row_idx in range(2, last_row + 1):
            dismissed_cell = ws.cell(row=row_idx, column=dismissed_col_idx + 1)
            if dismissed_cell.value is True:
                ws.row_dimensions[row_idx].hidden = True

        ws.add_table(table)

    # Auto-size columns (approximate)
    for col_idx, header in enumerate(headers, 1):
        max_len = len(header)
        for row in ws.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
            for cell in row:
                if cell.value:
                    max_len = max(max_len, min(len(str(cell.value)), 60))
        ws.column_dimensions[get_column_letter(col_idx)].width = max_len + 3

    buf = BytesIO()
    wb.save(buf)
    content = buf.getvalue()

    prefix = "enhanced-insights" if enhanced_only else "insights"
    filename = f"{prefix}-{session.name.replace(' ', '_')}.xlsx"

    return StreamingResponse(
        _stream_bytes(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/summary-export")
async def export_summary(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Export a full session briefing as HTML. Generated in-memory, never stored."""
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    synthesis_result = await db.execute(
        select(SessionSynthesis)
        .where(SessionSynthesis.session_id == session_id, SessionSynthesis.mode == "post_call")
        .options(selectinload(SessionSynthesis.clusters))
    )
    synthesis = synthesis_result.scalar_one_or_none()

    if synthesis and _synthesis_is_usable(synthesis):
        html = _render_synthesis_html(session, synthesis)
        prefix = "briefing"
    else:
        html = await _render_legacy_summary_html(session, session_id, db)
        prefix = "summary"

    content = html.encode("utf-8")
    filename = f"{prefix}-{session.name.replace(' ', '_')}.html"

    return StreamingResponse(
        _stream_bytes(content),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "N/A"


def _synthesis_is_usable(synthesis: SessionSynthesis) -> bool:
    if synthesis.status not in {"completed", "partial"}:
        return False
    sections = [
        synthesis.top_outcomes,
        synthesis.client_objectives,
        synthesis.top_opportunities,
        synthesis.risks_blockers,
        synthesis.action_plan,
        synthesis.unresolved_discovery_questions,
    ]
    return any(_section_has_content(section) for section in sections) or bool(synthesis.clusters)


def _section_has_content(items: list | None) -> bool:
    return any(
        isinstance(item, dict) and bool(item.get("title") or item.get("summary"))
        for item in (items or [])
    )


# Self-contained stylesheet for exported briefing/summary documents. No external
# fonts or CDN assets so the file renders offline (downloaded, emailed, printed).
# Teal accent matches the Backchannel product palette; light + dark + print.
_DOC_STYLE = """
:root {
  color-scheme: light dark;
  --font-sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, "SFMono-Regular", "Cascadia Code", "Segoe UI Mono", Menlo, Consolas, monospace;
  --canvas: #f4f6f5;
  --surface: #ffffff;
  --ink: #1a1e1d;
  --ink-soft: #556260;
  --ink-faint: #8b9693;
  --line: #e7ebea;
  --line-soft: #f0f3f2;
  --accent: #0d9488;
  --accent-strong: #0f766e;
  --note-bg: #fffbeb;
  --note-border: #f59e0b;
  --note-ink: #7c5410;
  --shadow: 0 1px 2px rgba(16,24,23,.05), 0 14px 34px -18px rgba(16,24,23,.22);
  --radius-sheet: 16px;
  --radius: 10px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --canvas: #0c0e0e;
    --surface: #15191a;
    --ink: #e8ecea;
    --ink-soft: #9aa5a2;
    --ink-faint: #6a7573;
    --line: #262d2c;
    --line-soft: #1d2322;
    --accent: #2dd4bf;
    --accent-strong: #5eead4;
    --note-bg: #241d0c;
    --note-border: #a16207;
    --note-ink: #fcd34d;
    --shadow: 0 1px 2px rgba(0,0,0,.35), 0 16px 36px -18px rgba(0,0,0,.65);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 40px 20px;
  background: var(--canvas); color: var(--ink);
  font-family: var(--font-sans); font-size: 16px; line-height: 1.6;
  -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
}
.sheet {
  max-width: 840px; margin: 0 auto; padding: 56px 56px 40px;
  background: var(--surface); border-radius: var(--radius-sheet); box-shadow: var(--shadow);
}
.kicker {
  margin: 0 0 16px; display: flex; align-items: center; gap: 10px;
  font-family: var(--font-mono); font-size: 11px; letter-spacing: .2em;
  text-transform: uppercase; color: var(--accent-strong);
}
.kicker::before { content: ""; width: 24px; height: 2px; border-radius: 2px; background: var(--accent); }
h1 {
  margin: 0 0 16px; font-size: clamp(28px, 4vw, 38px); line-height: 1.08;
  letter-spacing: -.022em; font-weight: 680; text-wrap: balance;
}
.meta { margin: 0; color: var(--ink-soft); font-size: 13px; font-family: var(--font-mono); }
.meta .sep { color: var(--ink-faint); margin: 0 8px; }
.rule { height: 1px; margin: 28px 0 0; border: 0; background: var(--line); }
.stats {
  display: flex; flex-wrap: wrap; margin: 28px 0 0;
  border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden;
}
.stat { flex: 1 1 0; min-width: 92px; padding: 16px 20px; border-right: 1px solid var(--line-soft); }
.stat:last-child { border-right: 0; }
.stat-value { font-size: 26px; font-weight: 680; letter-spacing: -.02em; font-variant-numeric: tabular-nums; line-height: 1; }
.stat-label { margin-top: 6px; font-size: 11px; letter-spacing: .09em; text-transform: uppercase; color: var(--ink-faint); }
.stat.primary .stat-value { color: var(--accent-strong); }
section { margin-top: 40px; }
h2 {
  display: flex; align-items: baseline; gap: 11px; margin: 0 0 18px;
  padding-bottom: 11px; border-bottom: 1px solid var(--line);
  font-size: 18px; letter-spacing: -.012em; font-weight: 660;
}
h2::before { content: ""; width: 8px; height: 8px; border-radius: 2px; background: var(--accent); align-self: center; flex: none; }
h2 .count { margin-left: auto; font-family: var(--font-mono); font-size: 12px; font-weight: 400; color: var(--ink-faint); }
.record { display: grid; grid-template-columns: 30px 1fr; gap: 0 14px; padding: 18px 0; border-top: 1px solid var(--line-soft); }
.record:first-of-type { border-top: 0; padding-top: 6px; }
.idx { padding-top: 3px; font-family: var(--font-mono); font-size: 12.5px; color: var(--accent-strong); font-variant-numeric: tabular-nums; }
.title { font-weight: 640; font-size: 15.5px; line-height: 1.4; }
.body { margin: 6px 0 0; }
.rationale { margin: 6px 0 0; color: var(--ink-soft); font-size: 14px; }
.rmeta { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 9px; font-family: var(--font-mono); font-size: 12.5px; color: var(--ink-soft); }
.chip { display: inline-flex; align-items: center; gap: 7px; }
.chip .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
.empty { color: var(--ink-faint); font-style: italic; }
.note {
  margin-top: 4px; padding: 14px 16px; border-left: 3px solid var(--note-border);
  border-radius: 0 var(--radius) var(--radius) 0; background: var(--note-bg);
  color: var(--note-ink); font-size: 14.5px; line-height: 1.55;
}
table { width: 100%; margin: 0; border-collapse: collapse; font-size: 14px; }
thead th { padding: 0 10px 10px; text-align: left; font-size: 11px; letter-spacing: .07em; text-transform: uppercase; font-weight: 600; color: var(--ink-faint); border-bottom: 1px solid var(--line); }
tbody td { padding: 13px 10px; vertical-align: top; border-bottom: 1px solid var(--line-soft); }
tbody tr:last-child td { border-bottom: 0; }
td.star { width: 22px; }
.starred { color: var(--accent); }
td.rationale-cell { color: var(--ink-soft); }
td.src em { font-style: normal; font-family: var(--font-mono); font-size: 12px; color: var(--ink-faint); }
.dismissed { font-family: var(--font-mono); font-size: 12px; color: var(--ink-faint); }
.transcript p { margin: 0 0 11px; }
.transcript .ts { margin-right: 9px; font-family: var(--font-mono); font-size: 12px; color: var(--ink-faint); }
.foot { display: flex; justify-content: space-between; gap: 16px; margin-top: 46px; padding-top: 18px; border-top: 1px solid var(--line); font-family: var(--font-mono); font-size: 12px; color: var(--ink-faint); }
@media (max-width: 640px) {
  body { padding: 0; }
  .sheet { padding: 32px 22px; border-radius: 0; box-shadow: none; }
}
@media print {
  body { padding: 0; background: #fff; color: #111; font-size: 11.5pt; }
  .sheet { max-width: none; padding: 0; border-radius: 0; box-shadow: none; }
  .note { background: #fff; }
  section, .record, tr, .transcript p { break-inside: avoid; }
  h1, h2 { break-after: avoid; }
}
"""


def _count(items) -> int:
    return sum(
        1 for it in (items or [])
        if isinstance(it, dict) and (it.get("title") or it.get("summary"))
    )


def _document(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>"
        f"<style>{_DOC_STYLE}</style></head>"
        f'<body><main class="sheet">{body}</main></body></html>'
    )


def _masthead(kicker: str, title: str, meta_parts: list[str]) -> str:
    meta = '<span class="sep">&middot;</span>'.join(meta_parts)
    return (
        f'<p class="kicker">{escape(kicker)}</p>'
        f"<h1>{escape(title)}</h1>"
        f'<p class="meta">{meta}</p>'
        '<hr class="rule">'
    )


def _stat_strip(stats: list[tuple[str, int, bool]]) -> str:
    cells = []
    for label, value, primary in stats:
        cls = "stat primary" if primary else "stat"
        cells.append(
            f'<div class="{cls}"><div class="stat-value">{value}</div>'
            f'<div class="stat-label">{escape(label)}</div></div>'
        )
    return f'<div class="stats">{"".join(cells)}</div>'


def _footer() -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        '<footer class="foot"><span>Generated by Backchannel</span>'
        f"<span>{generated}</span></footer>"
    )


def _render_section(title: str, items: list) -> str:
    valid = [
        it for it in (items or [])
        if isinstance(it, dict) and (it.get("title") or it.get("summary"))
    ]
    head = f'<h2>{escape(title)}<span class="count">{len(valid)}</span></h2>'
    if not valid:
        return f'<section>{head}<p class="empty">No items captured.</p></section>'
    records = []
    for i, item in enumerate(valid, 1):
        item_title = escape(str(item.get("title") or ""))
        summary = escape(str(item.get("summary") or ""))
        rationale = escape(str(item.get("rationale") or ""))
        owner = escape(str(item.get("owner") or ""))
        status = escape(str(item.get("status") or ""))
        meta_bits = []
        if owner:
            meta_bits.append(f'<span class="owner">{owner}</span>')
        if status:
            meta_bits.append(f'<span class="chip"><span class="dot"></span>{status}</span>')
        rmeta = f'<div class="rmeta">{"".join(meta_bits)}</div>' if meta_bits else ""
        title_html = f'<div class="title">{item_title}</div>' if item_title else ""
        summary_html = f'<p class="body">{summary}</p>' if summary else ""
        rationale_html = f'<p class="rationale">{rationale}</p>' if rationale else ""
        records.append(
            f'<div class="record"><div class="idx">{i:02d}</div><div class="rmain">'
            f"{title_html}{rmeta}{summary_html}{rationale_html}</div></div>"
        )
    return f'<section>{head}{"".join(records)}</section>'


def _render_synthesis_html(session: Session, synthesis: SessionSynthesis) -> str:
    labels = _briefing_section_labels(getattr(session, "meeting_type", "general"))
    masthead = _masthead(
        "Backchannel Briefing",
        session.name,
        [
            f"Started {_fmt(session.started_at)}",
            f"Ended {_fmt(session.ended_at)}",
            f"Status: {escape(synthesis.status)}",
        ],
    )
    stat_strip = _stat_strip([
        ("Outcomes", _count(synthesis.top_outcomes), False),
        ("Opportunities", _count(synthesis.top_opportunities), False),
        ("Risks", _count(synthesis.risks_blockers), False),
        ("Actions", _count(synthesis.action_plan), True),
        ("Questions", _count(synthesis.unresolved_discovery_questions), False),
    ])
    sections = "".join([
        _render_section("Top Outcomes", synthesis.top_outcomes),
        _render_section(labels["objectives"], synthesis.client_objectives),
        _render_section(labels["opportunities"], synthesis.top_opportunities),
        _render_section("Risks / Blockers", synthesis.risks_blockers),
        _render_section("Action Plan", synthesis.action_plan),
        _render_section(labels["questions"], synthesis.unresolved_discovery_questions),
    ])

    clusters = ""
    if synthesis.clusters:
        records = []
        for i, cluster in enumerate(synthesis.clusters, 1):
            confidence = escape(str(cluster.confidence or ""))
            conf_html = (
                f'<div class="rmeta"><span class="chip"><span class="dot"></span>'
                f"Confidence: {confidence}</span></div>"
                if confidence else ""
            )
            records.append(
                f'<div class="record"><div class="idx">{i:02d}</div><div class="rmain">'
                f'<div class="title">{escape(cluster.title)}</div>{conf_html}'
                f'<p class="body">{escape(cluster.summary)}</p></div></div>'
            )
        clusters = (
            f'<section><h2>Insight Clusters<span class="count">{len(synthesis.clusters)}</span></h2>'
            f'{"".join(records)}</section>'
        )

    notes = escape(synthesis.arbiter_notes or "No arbiter notes captured.")
    notes_section = f'<section><h2>Arbiter Notes</h2><div class="note">{notes}</div></section>'

    body = masthead + stat_strip + sections + clusters + notes_section + _footer()
    return _document(f"Call Briefing - {session.name}", body)


def _briefing_section_labels(meeting_type: str) -> dict[str, str]:
    if meeting_type == "internal_enablement":
        return {
            "objectives": "Learning Objectives",
            "opportunities": "Enablement Opportunities",
            "questions": "Open Learning Questions",
        }
    if meeting_type == "internal_checkin":
        return {
            "objectives": "Objectives / Needs",
            "opportunities": "Support Opportunities",
            "questions": "Open Questions",
        }
    if meeting_type == "vendor_partner":
        return {
            "objectives": "Vendor / Program Objectives",
            "opportunities": "Partner Opportunities",
            "questions": "Open Vendor / Program Questions",
        }
    if meeting_type == "customer_delivery":
        return {
            "objectives": "Project Objectives",
            "opportunities": "Delivery Opportunities",
            "questions": "Open Delivery Questions",
        }
    if meeting_type == "client_sales":
        return {
            "objectives": "Client Objectives",
            "opportunities": "Top Opportunities",
            "questions": "Unresolved Discovery Questions",
        }
    return {
        "objectives": "Objectives",
        "opportunities": "Top Opportunities",
        "questions": "Open Questions",
    }


async def _render_legacy_summary_html(session: Session, session_id: uuid.UUID, db: AsyncSession) -> str:
    t_result = await db.execute(
        select(TranscriptEntry).where(TranscriptEntry.session_id == session_id).order_by(TranscriptEntry.sequence)
    )
    transcripts = t_result.scalars().all()

    q_result = await db.execute(
        select(Question).where(Question.session_id == session_id).order_by(Question.created_at)
    )
    questions = q_result.scalars().all()

    starred = [q for q in questions if q.starred]

    masthead = _masthead(
        "Session Summary",
        session.name,
        [f"Started {_fmt(session.started_at)}", f"Ended {_fmt(session.ended_at)}"],
    )
    stat_strip = _stat_strip([
        ("Questions", len(questions), True),
        ("Starred", len(starred), False),
        ("Transcript Lines", len(transcripts), False),
    ])

    if questions:
        rows = ""
        for q in questions:
            star = '<span class="starred">&#9733;</span>' if q.starred else ""
            dismissed = ' <span class="dismissed">(dismissed)</span>' if q.dismissed else ""
            rows += (
                "<tr>"
                f'<td class="star">{star}</td>'
                f"<td>{escape(q.question)}{dismissed}</td>"
                f'<td class="rationale-cell">{escape(q.rationale)}</td>'
                f'<td class="src"><em>{escape(q.source_context)}</em></td>'
                "</tr>"
            )
        questions_section = (
            f'<section><h2>Questions<span class="count">{len(questions)}</span></h2>'
            '<table><thead><tr><th class="star"></th><th>Question</th>'
            "<th>Rationale</th><th>Source Context</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></section>"
        )
    else:
        questions_section = '<section><h2>Questions</h2><p class="empty">No questions captured.</p></section>'

    if transcripts:
        lines = ""
        for t in transcripts:
            ts = t.timestamp.strftime("%H:%M:%S") if t.timestamp else ""
            lines += f'<p><span class="ts">[{escape(ts)}]</span>{escape(t.text)}</p>'
        transcript_section = (
            f'<section><h2>Transcript<span class="count">{len(transcripts)}</span></h2>'
            f'<div class="transcript">{lines}</div></section>'
        )
    else:
        transcript_section = '<section><h2>Transcript</h2><p class="empty">No transcript recorded.</p></section>'

    body = masthead + stat_strip + questions_section + transcript_section + _footer()
    return _document(f"Call Summary - {session.name}", body)
