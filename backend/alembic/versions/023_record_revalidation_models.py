"""Record requested and actual insight-revalidation models.

Revision ID: 023_revalidation_models
Revises: 022_document_summaries
Create Date: 2026-08-02
"""

import sqlalchemy as sa

from alembic import op

revision = "023_revalidation_models"
down_revision = "022_document_summaries"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "speaker_revalidation_batches",
        sa.Column("requested_model_id", sa.String(160), nullable=True),
    )
    op.add_column(
        "speaker_revalidation_batches",
        sa.Column("model_id", sa.String(160), nullable=True),
    )


def downgrade():
    op.drop_column("speaker_revalidation_batches", "model_id")
    op.drop_column("speaker_revalidation_batches", "requested_model_id")
