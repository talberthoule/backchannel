"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-16
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("state", sa.String(20), server_default="pre_call"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("gemini_file_uri", sa.String(500), server_default=""),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "directives",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "transcript_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("sequence", sa.Integer, server_default="0"),
    )

    op.create_table(
        "questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("rationale", sa.Text, server_default=""),
        sa.Column("source_context", sa.Text, server_default=""),
        sa.Column("directive_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("directives.id"), nullable=True),
        sa.Column("starred", sa.Boolean, server_default="false"),
        sa.Column("dismissed", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("questions")
    op.drop_table("transcript_entries")
    op.drop_table("directives")
    op.drop_table("documents")
    op.drop_table("sessions")
