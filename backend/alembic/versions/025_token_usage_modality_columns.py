"""Record the cached and audio slices of a usage row.

Providers bill cached prompt tokens at a fraction of the text rate and audio
tokens at a multiple of it, and both were being priced at the text rate: the
live audio gateway's input, which is almost entirely audio, was estimated at a
quarter of its published price. The three columns are subsets of input_tokens
(cached, audio) and output_tokens (audio), not additions to them.

Guarded with an inspector because app.main._add_missing_columns adds these
columns at startup as well: on any deployment that has booted since the code
landed, they already exist by the time alembic runs.

Revision ID: 025_token_usage_modalities
Revises: 024_token_usage_audio_seconds
Create Date: 2026-09-01
"""

import sqlalchemy as sa

from alembic import op

revision = "025_token_usage_modalities"
down_revision = "024_token_usage_audio_seconds"
branch_labels = None
depends_on = None

COLUMNS = ("cached_input_tokens", "audio_input_tokens", "audio_output_tokens")


def _existing_columns() -> set[str] | None:
    inspector = sa.inspect(op.get_bind())
    if "token_usage" not in inspector.get_table_names():
        return None
    return {column["name"] for column in inspector.get_columns("token_usage")}


def upgrade():
    existing = _existing_columns()
    if existing is None:
        return
    for name in COLUMNS:
        if name in existing:
            continue
        op.add_column(
            "token_usage",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade():
    existing = _existing_columns()
    if existing is None:
        return
    for name in COLUMNS:
        if name in existing:
            op.drop_column("token_usage", name)
