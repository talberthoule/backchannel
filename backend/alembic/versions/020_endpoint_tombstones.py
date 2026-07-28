"""Retain deleted custom endpoint identities.

Revision ID: 020_endpoint_tombstones
Revises: 019_custom_endpoints
Create Date: 2026-07-28
"""

import sqlalchemy as sa

from alembic import op

revision = "020_endpoint_tombstones"
down_revision = "019_custom_endpoints"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "custom_endpoints",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("custom_endpoints", "deleted_at")
