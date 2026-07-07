"""add offering discipline

Revision ID: 009
Revises: 008
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "offerings",
        sa.Column("discipline", sa.String(length=255), nullable=False, server_default=""),
    )


def downgrade():
    op.drop_column("offerings", "discipline")
