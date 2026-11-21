"""Phase 3 domain models: smart flashcards with SM-2 spaced repetition.

- ``flashcard_decks`` — a student's deck (optionally tied to a book / chapter /
  printed-page range, and tagged with where the cards came from).
- ``flashcards`` — one card: Persian Markdown + LaTeX front/back, optional hint,
  server-owned textbook ``citations_json`` and tags.
- ``flashcard_reviews`` — per (card, user) SM-2 scheduling state. Rows are created
  on the first rating; a card with no row is "new" and due immediately.

Admin moderation flags (``is_public``, ``admin_approved``) only allow an admin to
publish a deck to the shared library; students cannot self-publish.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_json_type = JSON().with_variant(JSONB, "postgresql")

SOURCE_TYPES: tuple[str, ...] = ("book", "chat", "mistake", "manual")


class FlashcardDeck(Base):
    __tablename__ = "flashcard_decks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id"), nullable=True, index=True)
    chapter_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    admin_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Flashcard(Base):
    __tablename__ = "flashcards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deck_id: Mapped[int] = mapped_column(
        ForeignKey("flashcard_decks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    front_md: Mapped[str] = mapped_column(Text, nullable=False)
    back_md: Mapped[str] = mapped_column(Text, nullable=False)
    hint_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _json_type, nullable=False, default=list
    )
    tags_json: Mapped[list[str]] = mapped_column(_json_type, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FlashcardReview(Base):
    __tablename__ = "flashcard_reviews"
    __table_args__ = (
        UniqueConstraint("card_id", "user_id", name="uq_flashcard_reviews_card_user"),
        Index("ix_flashcard_reviews_user_next", "user_id", "next_review_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("flashcards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    ease_factor: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_review_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
