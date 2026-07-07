"""add speaker type

Revision ID: 007
Revises: 006
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "speakers",
        sa.Column("speaker_type", sa.String(length=20), nullable=False, server_default="external"),
    )
    op.execute("UPDATE speakers SET speaker_type = 'team' WHERE is_user = true")


def downgrade():
    op.drop_column("speakers", "speaker_type")
