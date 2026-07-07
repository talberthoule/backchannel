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
            type_labels.get(q.item_type, q.item_type or "Question"),
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


def _render_section(title: str, items: list) -> str:
    if not items:
        return f"<h2>{escape(title)}</h2><p class='muted'>No items captured.</p>"
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_title = escape(str(item.get("title") or ""))
        summary = escape(str(item.get("summary") or ""))
        rationale = escape(str(item.get("rationale") or ""))
        owner = escape(str(item.get("owner") or ""))
        status = escape(str(item.get("status") or ""))
        meta = " &middot; ".join(part for part in [owner, status] if part)
        meta_html = f'<div class="meta">{meta}</div>' if meta else ""
        rationale_html = f'<p class="muted">{rationale}</p>' if rationale else ""
        rows.append(
            "<li>"
            f"<strong>{item_title}</strong>"
            f"{meta_html}"
            f"<p>{summary}</p>"
            f"{rationale_html}"
            "</li>"
        )
    return f"<h2>{escape(title)}</h2><ul>{''.join(rows)}</ul>"


def _render_synthesis_html(session: Session, synthesis: SessionSynthesis) -> str:
    labels = _briefing_section_labels(getattr(session, "meeting_type", "general"))
    sections = [
        _render_section("Top Outcomes", synthesis.top_outcomes),
        _render_section(labels["objectives"], synthesis.client_objectives),
        _render_section(labels["opportunities"], synthesis.top_opportunities),
        _render_section("Risks / Blockers", synthesis.risks_blockers),
        _render_section("Action Plan", synthesis.action_plan),
        _render_section(labels["questions"], synthesis.unresolved_discovery_questions),
    ]
    clusters = ""
    if synthesis.clusters:
        cluster_rows = []
        for cluster in synthesis.clusters:
            cluster_rows.append(
                "<li>"
                f"<strong>{escape(cluster.title)}</strong>"
                f"<p>{escape(cluster.summary)}</p>"
                f"<p class='muted'>Confidence: {escape(cluster.confidence)}</p>"
                "</li>"
            )
        clusters = f"<h2>Insight Clusters</h2><ul>{''.join(cluster_rows)}</ul>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Call Briefing - {escape(session.name)}</title>
<style>
body {{ font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #333; }}
h1 {{ font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #0f766e; }}
h2 {{ font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #0d9488; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; }}
li {{ margin-bottom: 1rem; }}
.meta, .muted {{ color: #5f6062; font-size: 0.9rem; }}
.note {{ border-left: 4px solid #f59e0b; background: #fff7ed; padding: 0.75rem 1rem; }}
</style></head><body>
<h1>{escape(session.name)}</h1>
<p class="meta">Started: {_fmt(session.started_at)} &middot; Ended: {_fmt(session.ended_at)} &middot; Briefing status: {escape(synthesis.status)}</p>
{''.join(sections)}
{clusters}
<h2>Arbiter Notes</h2>
<div class="note">{escape(synthesis.arbiter_notes or "No arbiter notes captured.")}</div>
<hr style="margin-top:2rem;border:none;border-top:1px solid #e2e8f0">
<p class="muted">Generated by Backchannel.</p>
</body></html>"""


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

    question_rows = ""
    for q in questions:
        star = "&#9733;" if q.starred else ""
        dismissed = " (dismissed)" if q.dismissed else ""
        question_rows += f"""<tr>
            <td>{star}</td>
            <td>{escape(q.question)}{escape(dismissed)}</td>
            <td>{escape(q.rationale)}</td>
            <td><em>{escape(q.source_context)}</em></td>
        </tr>"""

    transcript_lines = ""
    for t in transcripts:
        ts = t.timestamp.strftime("%H:%M:%S") if t.timestamp else ""
        transcript_lines += f"<p><span style='color:#999;font-family:monospace'>[{escape(ts)}]</span> {escape(t.text)}</p>\n"

    html = f"""<!DOCTYPE html>
    <html><head><meta charset="utf-8"><title>Call Summary - {escape(session.name)}</title>
<style>
body {{ font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #333; }}
h1 {{ font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #0f766e; }}
h2 {{ font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #0d9488; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; }}
table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
th, td {{ text-align: left; padding: 0.5rem; border-bottom: 1px solid #e2e8f0; font-size: 0.9rem; }}
th {{ background: #f8fafc; font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; font-size: 0.8rem; text-transform: uppercase; }}
.meta {{ color: #5f6062; font-size: 0.9rem; }}
.stats {{ display: flex; gap: 2rem; margin: 1rem 0; }}
.stat {{ text-align: center; }}
.stat-value {{ font-size: 1.5rem; font-weight: bold; color: #0d9488; }}
.stat-label {{ font-size: 0.75rem; color: #999; text-transform: uppercase; }}
</style></head><body>
    <h1>{escape(session.name)}</h1>
    <p class="meta">Started: {_fmt(session.started_at)} &middot; Ended: {_fmt(session.ended_at)}</p>
<div class="stats">
    <div class="stat"><div class="stat-value">{len(questions)}</div><div class="stat-label">Questions</div></div>
    <div class="stat"><div class="stat-value">{len(starred)}</div><div class="stat-label">Starred</div></div>
    <div class="stat"><div class="stat-value">{len(transcripts)}</div><div class="stat-label">Transcript Lines</div></div>
</div>
<h2>Questions</h2>
<table><tr><th></th><th>Question</th><th>Rationale</th><th>Source Context</th></tr>
{question_rows}
</table>
<h2>Transcript</h2>
{transcript_lines if transcript_lines else "<p style='color:#999'>No transcript recorded.</p>"}
<hr style="margin-top:2rem;border:none;border-top:1px solid #e2e8f0">
    <p style="font-size:0.75rem;color:#999">Generated by Backchannel.</p>
    </body></html>"""
    return html
