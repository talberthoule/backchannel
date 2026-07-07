"""Add call_segments.audio_path for persisted segment audio

Revision ID: 012
Revises: 011
"""

import sqlalchemy as sa
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("call_segments", sa.Column("audio_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("call_segments", "audio_path")
