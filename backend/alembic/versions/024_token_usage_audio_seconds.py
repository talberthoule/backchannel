"""Record audio duration for models billed per minute rather than per token.

OpenAI Realtime transcription reports usage as a duration payload, which the
token-only row could not represent, so the usage was dropped and the agent
showed no cost at all (ALP-300).

Guarded with an inspector because app.main._add_missing_columns adds this
column at startup as well: on any deployment that has booted since the code
landed, the column already exists by the time alembic runs.

Revision ID: 024_token_usage_audio_seconds
Revises: 023_revalidation_models
Create Date: 2026-08-14
"""

import sqlalchemy as sa

from alembic import op

revision = "024_token_usage_audio_seconds"
down_revision = "023_revalidation_models"
branch_labels = None
depends_on = None


def _has_column(name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if "token_usage" not in inspector.get_table_names():
        return True
    return name in {column["name"] for column in inspector.get_columns("token_usage")}


def upgrade():
    if _has_column("audio_seconds"):
        return
    op.add_column(
        "token_usage",
        sa.Column("audio_seconds", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade():
    if not _has_column("audio_seconds"):
        return
    op.drop_column("token_usage", "audio_seconds")
