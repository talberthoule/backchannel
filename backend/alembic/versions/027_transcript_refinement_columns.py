"""Transcript refinement: keep the transcriber's text beside the refined one.

The transcript refiner rewrites an entry's text (already tokenized by the
PII Shield) for punctuation, casing and obvious mishearings. raw_text holds
what the transcriber wrote, set once on first refinement; refined_at says
when the current text was produced.

Guarded with an inspector because app.main._add_missing_columns adds these
columns at startup as well.

Revision ID: 027_transcript_refinement
Revises: 026_pii_shield_tables
Create Date: 2026-09-02
"""

import sqlalchemy as sa

from alembic import op

revision = "027_transcript_refinement"
down_revision = "026_pii_shield_tables"
branch_labels = None
depends_on = None


def _existing_columns() -> set[str] | None:
    inspector = sa.inspect(op.get_bind())
    if "transcript_entries" not in inspector.get_table_names():
        return None
    return {column["name"] for column in inspector.get_columns("transcript_entries")}


def upgrade():
    existing = _existing_columns()
    if existing is None:
        return
    if "raw_text" not in existing:
        op.add_column("transcript_entries", sa.Column("raw_text", sa.Text(), nullable=True))
    if "refined_at" not in existing:
        op.add_column("transcript_entries", sa.Column("refined_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    existing = _existing_columns()
    if existing is None:
        return
    if "refined_at" in existing:
        op.drop_column("transcript_entries", "refined_at")
    if "raw_text" in existing:
        op.drop_column("transcript_entries", "raw_text")
