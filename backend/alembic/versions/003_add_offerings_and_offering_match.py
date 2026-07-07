"""Add offerings table and offering_match column to questions

Revision ID: 003
Revises: 002
Create Date: 2026-03-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    # Add offering_match to questions
    op.add_column(
        "questions",
        sa.Column("offering_match", sa.Text, server_default="", nullable=False),
    )

    # Create offerings table
    op.create_table(
        "offerings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vendor", sa.String(100), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("subcategory", sa.String(100), server_default=""),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("use_cases", sa.Text, server_default=""),
        sa.Column("delivery_model", sa.String(100), server_default=""),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_table("offerings")
    op.drop_column("questions", "offering_match")
