"""Add split-track audio paths to call segments.

Revision ID: 016
Revises: 015
"""

import sqlalchemy as sa
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("call_segments", sa.Column("mic_audio_path", sa.String(length=500), nullable=True))
    op.add_column("call_segments", sa.Column("system_audio_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("call_segments", "system_audio_path")
    op.drop_column("call_segments", "mic_audio_path")
