"""Add agent_source column to questions

Revision ID: 002
Revises: 001
Create Date: 2026-03-21
"""

import sqlalchemy as sa

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "questions",
        sa.Column("agent_source", sa.String(30), server_default="general", nullable=False),
    )


def downgrade():
    op.drop_column("questions", "agent_source")
