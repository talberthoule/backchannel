"""Add durable strategic signal history.

Revision ID: 021_signal_history
Revises: 020_endpoint_tombstones
Create Date: 2026-07-30
"""

import sqlalchemy as sa

from alembic import op


revision = "021_signal_history"
down_revision = "020_endpoint_tombstones"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "session_syntheses",
        sa.Column(
            "signal_history",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade():
    op.drop_column("session_syntheses", "signal_history")
