"""Rename offering fields: merge discipline into subcategory, practice -> tags, delivery_model -> note

Revision ID: 015
Revises: 014
Create Date: 2026-07-07
"""

import sqlalchemy as sa

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "offerings",
        "subcategory",
        existing_type=sa.String(length=100),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    op.execute(
        "UPDATE offerings SET subcategory = discipline WHERE subcategory = '' AND discipline <> ''"
    )
    op.drop_column("offerings", "discipline")
    op.alter_column(
        "offerings",
        "delivery_model",
        new_column_name="note",
        existing_type=sa.String(length=100),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    op.alter_column(
        "offerings",
        "practice",
        new_column_name="tags",
        existing_type=sa.String(length=255),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        "offerings",
        "tags",
        new_column_name="practice",
        existing_type=sa.String(length=255),
        existing_nullable=False,
    )
    op.alter_column(
        "offerings",
        "note",
        new_column_name="delivery_model",
        existing_type=sa.String(length=255),
        type_=sa.String(length=100),
        existing_nullable=False,
    )
    op.add_column(
        "offerings",
        sa.Column("discipline", sa.String(length=255), nullable=False, server_default=""),
    )
    op.alter_column(
        "offerings",
        "subcategory",
        existing_type=sa.String(length=255),
        type_=sa.String(length=100),
        existing_nullable=False,
    )
