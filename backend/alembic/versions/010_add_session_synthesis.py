"""add session synthesis

Revision ID: 010
Revises: 009
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "session_syntheses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="post_call"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("top_outcomes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("client_objectives", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("top_opportunities", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("risks_blockers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("action_plan", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("unresolved_discovery_questions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("strategic_signals", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("lens_meeting", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("lens_discovery", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("arbiter_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("model_ids", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("session_id", "mode", name="uq_session_syntheses_session_mode"),
    )
    op.create_table(
        "insight_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("synthesis_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("session_syntheses.id"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("related_question_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("insight_clusters")
    op.drop_table("session_syntheses")
