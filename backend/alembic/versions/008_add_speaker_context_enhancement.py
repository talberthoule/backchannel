"""add speaker context enhancement state

Revision ID: 008
Revises: 007
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sessions",
        sa.Column("speaker_context_dirty", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "sessions",
        sa.Column("speaker_context_enhanced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "questions",
        sa.Column("enhanced", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade():
    op.drop_column("questions", "enhanced")
    op.drop_column("sessions", "speaker_context_enhanced_at")
    op.drop_column("sessions", "speaker_context_dirty")
