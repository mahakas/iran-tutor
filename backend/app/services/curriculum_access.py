"""Student-facing access policy for textbook catalogue status."""

from __future__ import annotations

from app.core.config import get_settings
from app.models.curriculum import Book, BookStatus


def allowed_student_catalog_statuses() -> tuple[str, ...]:
    """Only owner-reviewed official editions are available outside demo mode."""
    if get_settings().demo_mode:
        return ("approved", "demo")
    return ("approved",)


def student_book_catalog_clause():
    return Book.catalog_status.in_(allowed_student_catalog_statuses())


def is_student_visible_book(book: Book | None) -> bool:
    return bool(
        book is not None
        and book.status == BookStatus.ready
        and book.catalog_status in allowed_student_catalog_statuses()
    )
