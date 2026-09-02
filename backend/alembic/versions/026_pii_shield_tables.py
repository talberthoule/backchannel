"""PII Shield: the per-session vault and the reveal audit trail.

pii_vault_entries holds one row per protected value per session: the token
the models and the database see, and the real value encrypted under a key
derived from the DATA_DIR master key. pii_reveal_events is append-only and
records every substitution back to real values for the local interface.

Guarded with an inspector because Base.metadata.create_all at startup creates
both tables on any deployment that has booted since the code landed.

Revision ID: 026_pii_shield_tables
Revises: 025_token_usage_modalities
Create Date: 2026-09-02
"""

import sqlalchemy as sa

from alembic import op

revision = "026_pii_shield_tables"
down_revision = "025_token_usage_modalities"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "pii_vault_entries" not in existing:
        op.create_table(
            "pii_vault_entries",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id"), nullable=False),
            sa.Column("category", sa.String(20), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("token", sa.String(40), nullable=False),
            sa.Column("value_hmac", sa.String(64), nullable=False),
            sa.Column("value_encrypted", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("session_id", "value_hmac", name="uq_pii_vault_session_value"),
            sa.UniqueConstraint("session_id", "token", name="uq_pii_vault_session_token"),
        )
    if "pii_reveal_events" not in existing:
        op.create_table(
            "pii_reveal_events",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("session_id", sa.Uuid(), nullable=True),
            sa.Column("route", sa.String(160), nullable=False, server_default=""),
            sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "pii_reveal_events" in existing:
        op.drop_table("pii_reveal_events")
    if "pii_vault_entries" in existing:
        op.drop_table("pii_vault_entries")
