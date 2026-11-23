"""Flashcard study sessions: persistent NotebookLM-style study runs.

Creates ``flashcard_study_sessions`` (ordered card snapshot, position,
per-card Got/Missed results, flipped flag, lifecycle timestamps). No existing
table or row is altered, so SM-2 history and user data are preserved.

Revision ID: c9d0e1f2a3b4
Revises: b7c1d2e3f4a5
Create Date: 2026-11-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b7c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "flashcard_study_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "deck_id",
            sa.Integer(),
            sa.ForeignKey("flashcard_decks.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="full"),
        sa.Column("card_ids_json", JSON_TYPE, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("results_json", JSON_TYPE, nullable=False),
        sa.Column("flipped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="in_progress"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_flashcard_study_sessions_user_id", "flashcard_study_sessions", ["user_id"])
    op.create_index("ix_flashcard_study_sessions_deck_id", "flashcard_study_sessions", ["deck_id"])
    op.create_index(
        "ix_flashcard_study_sessions_user_status",
        "flashcard_study_sessions",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_flashcard_study_sessions_user_deck_mode_status",
        "flashcard_study_sessions",
        ["user_id", "deck_id", "mode", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_flashcard_study_sessions_user_deck_mode_status",
        table_name="flashcard_study_sessions",
    )
    op.drop_index("ix_flashcard_study_sessions_user_status", table_name="flashcard_study_sessions")
    op.drop_index("ix_flashcard_study_sessions_deck_id", table_name="flashcard_study_sessions")
    op.drop_index("ix_flashcard_study_sessions_user_id", table_name="flashcard_study_sessions")
    op.drop_table("flashcard_study_sessions")
