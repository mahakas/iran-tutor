"""Curriculum domain models: grades, majors, books, pages."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BookStatus(str, enum.Enum):
    created = "created"
    ingesting = "ingesting"
    ready = "ready"
    failed = "failed"


class PageStatus(str, enum.Enum):
    pending = "pending"
    done = "done"
    failed = "failed"
    needs_review = "needs_review"


class Grade(Base):
    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    has_major: Mapped[bool] = mapped_column(nullable=False)


class Major(Base):
    __tablename__ = "majors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    grade_id: Mapped[int] = mapped_column(ForeignKey("grades.id"), nullable=False)
    major_id: Mapped[int | None] = mapped_column(ForeignKey("majors.id"), nullable=True)
    pdf_file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    total_pdf_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[BookStatus] = mapped_column(
        Enum(BookStatus, name="book_status"), default=BookStatus.created, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BookPage(Base):
    __tablename__ = "book_pages"
    __table_args__ = (UniqueConstraint("book_id", "pdf_page_index", name="uq_bookpage_book_page"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    pdf_page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    markdown_content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    original_markdown_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    visual_elements: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False
    )
    page_image_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[PageStatus] = mapped_column(
        Enum(PageStatus, name="page_status"), default=PageStatus.pending, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warnings: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
    edited_by_human: Mapped[bool] = mapped_column(nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
