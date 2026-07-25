"""Add self-hosted OpenAI-compatible endpoints.

Each row is one reachable chat server; the models column lists what it serves,
and every entry becomes a selectable model id of the form
"endpoint:<slug>:<served model name>". Those ids are longer than the registry
ids the model_id columns were sized for, so both are widened here.

Revision ID: 019_custom_endpoints
Revises: 018_speaker_revalidation
Create Date: 2026-07-25
"""

import sqlalchemy as sa

from alembic import op

revision = "019_custom_endpoints"
down_revision = "018_speaker_revalidation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "custom_endpoints",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("models", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_status", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.alter_column(
        "agent_configs",
        "model_id",
        type_=sa.String(length=160),
        existing_type=sa.String(length=100),
        existing_nullable=False,
    )
    op.alter_column(
        "token_usage",
        "model_id",
        type_=sa.String(length=160),
        existing_type=sa.String(length=100),
        existing_nullable=False,
    )


def downgrade():
    # Endpoint model ids do not fit in the narrower column, so point any agent
    # still using one back at the default model before shrinking it.
    op.execute(
        "UPDATE agent_configs SET model_id = 'gemini-3.5-flash-lite' "
        "WHERE model_id LIKE 'endpoint:%'"
    )
    op.execute("DELETE FROM token_usage WHERE model_id LIKE 'endpoint:%'")
    op.alter_column(
        "token_usage",
        "model_id",
        type_=sa.String(length=100),
        existing_type=sa.String(length=160),
        existing_nullable=False,
    )
    op.alter_column(
        "agent_configs",
        "model_id",
        type_=sa.String(length=100),
        existing_type=sa.String(length=160),
        existing_nullable=False,
    )
    op.drop_table("custom_endpoints")
