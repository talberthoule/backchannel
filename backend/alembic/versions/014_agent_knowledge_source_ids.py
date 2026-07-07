"""Replace agent_configs.knowledge_source_id with comma-separated knowledge_source_ids

Revision ID: 014
Revises: 013
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agent_configs",
        sa.Column("knowledge_source_ids", sa.Text, nullable=False, server_default=""),
    )
    op.execute(
        "UPDATE agent_configs SET knowledge_source_ids = knowledge_source_id::text "
        "WHERE knowledge_source_id IS NOT NULL"
    )
    op.drop_column("agent_configs", "knowledge_source_id")


def downgrade():
    op.add_column(
        "agent_configs",
        sa.Column(
            "knowledge_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_sources.id"),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE agent_configs SET knowledge_source_id = split_part(knowledge_source_ids, ',', 1)::uuid "
        "WHERE knowledge_source_ids <> ''"
    )
    op.drop_column("agent_configs", "knowledge_source_ids")
