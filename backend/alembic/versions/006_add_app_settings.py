"""add app settings

Revision ID: 006
Revises: 005
Create Date: 2026-05-07
"""

from alembic import op
import sqlalchemy as sa


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_table("app_settings")
