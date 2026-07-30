"""Persist document summaries with their provenance.

Revision ID: 022_document_summaries
Revises: 021_signal_history
Create Date: 2026-07-30
"""

import sqlalchemy as sa

from alembic import op

revision = "022_document_summaries"
down_revision = "021_signal_history"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "documents",
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "documents",
        sa.Column("summary_source", sa.String(20), nullable=False, server_default=""),
    )


def downgrade():
    op.drop_column("documents", "summary_source")
    op.drop_column("documents", "summary")
