"""Add knowledge_sources/knowledge_records tables and agent knowledge_source_id

Revision ID: 013
Revises: 012
Create Date: 2026-07-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "knowledge_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("config", sa.Text, server_default="{}"),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "knowledge_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_sources.id"), nullable=False),
        sa.Column("title", sa.String(500), server_default=""),
        sa.Column("body", sa.Text, server_default=""),
        sa.Column("meta", sa.Text, server_default="{}"),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "agent_configs",
        sa.Column(
            "knowledge_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_sources.id"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("agent_configs", "knowledge_source_id")
    op.drop_table("knowledge_records")
    op.drop_table("knowledge_sources")
