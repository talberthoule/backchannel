"""Add vote to questions, display_name to speakers

Revision ID: 004
Revises: 003
Create Date: 2026-03-21
"""

import sqlalchemy as sa

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "questions",
        sa.Column("vote", sa.Integer, server_default="0", nullable=False),
    )
    op.add_column(
        "speakers",
        sa.Column("display_name", sa.String(255), server_default="", nullable=False),
    )
    op.add_column(
        "speakers",
        sa.Column("display_name_enabled", sa.Boolean, server_default="false", nullable=False),
    )


def downgrade():
    op.drop_column("speakers", "display_name_enabled")
    op.drop_column("speakers", "display_name")
    op.drop_column("questions", "vote")
