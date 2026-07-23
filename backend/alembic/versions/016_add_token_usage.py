"""Add per-session token usage records.

Revision ID: 016_token_usage
Revises: 015
Create Date: 2026-07-22
"""

import sqlalchemy as sa

from alembic import op

revision = "016_token_usage"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "token_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_token_usage_session_id"), "token_usage", ["session_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_token_usage_session_id"), table_name="token_usage")
    op.drop_table("token_usage")
