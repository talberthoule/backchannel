"""Add speaker attribution to questions

Revision ID: 005
Revises: 004
Create Date: 2026-05-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("questions", sa.Column("speaker_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_questions_speaker_id_speakers",
        "questions",
        "speakers",
        ["speaker_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint("fk_questions_speaker_id_speakers", "questions", type_="foreignkey")
    op.drop_column("questions", "speaker_id")
