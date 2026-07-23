"""Add observable speaker revalidation runs.

Revision ID: 018_speaker_revalidation
Revises: 017_token_usage
Create Date: 2026-07-23
"""

import sqlalchemy as sa

from alembic import op

revision = "018_speaker_revalidation"
down_revision = "017_token_usage"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sessions",
        sa.Column(
            "speaker_context_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_table(
        "speaker_mapping_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("mapping_hash", sa.String(length=64), nullable=False),
        sa.Column("mapping_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "source_version",
            name="uq_speaker_mapping_revision_session_version",
        ),
    )
    op.create_table(
        "speaker_revalidation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("mapping_revision_id", sa.Uuid(), nullable=False),
        sa.Column("content_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["mapping_revision_id"],
            ["speaker_mapping_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "mapping_revision_id",
            "content_version",
            name="uq_speaker_revalidation_run_revision",
        ),
    )
    op.create_table(
        "speaker_revalidation_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("item_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("processed_entries", sa.Integer(), nullable=False),
        sa.Column("applied_operations", sa.Integer(), nullable=False),
        sa.Column("enhanced_insights", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["speaker_revalidation_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "batch_index",
            name="uq_speaker_revalidation_batch_index",
        ),
    )
    op.add_column(
        "questions",
        sa.Column("speaker_mapping_revision_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_questions_speaker_mapping_revision",
        "questions",
        "speaker_mapping_revisions",
        ["speaker_mapping_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "session_syntheses",
        sa.Column("speaker_mapping_revision_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_session_syntheses_speaker_mapping_revision",
        "session_syntheses",
        "speaker_mapping_revisions",
        ["speaker_mapping_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_session_syntheses_speaker_mapping_revision",
        "session_syntheses",
        type_="foreignkey",
    )
    op.drop_column("session_syntheses", "speaker_mapping_revision_id")
    op.drop_constraint(
        "fk_questions_speaker_mapping_revision",
        "questions",
        type_="foreignkey",
    )
    op.drop_column("questions", "speaker_mapping_revision_id")
    op.drop_table("speaker_revalidation_batches")
    op.drop_table("speaker_revalidation_runs")
    op.drop_table("speaker_mapping_revisions")
    op.drop_column("sessions", "speaker_context_version")
