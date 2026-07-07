"""add session meeting context

Revision ID: 011
Revises: 010
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sessions",
        sa.Column("meeting_type", sa.String(length=50), nullable=False, server_default="general"),
    )
    op.add_column(
        "sessions",
        sa.Column("meeting_context", sa.Text(), nullable=False, server_default=""),
    )


def downgrade():
    op.drop_column("sessions", "meeting_context")
    op.drop_column("sessions", "meeting_type")
