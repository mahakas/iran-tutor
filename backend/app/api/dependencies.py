"""Shared API-level validation for curriculum-scoped requests."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import Book, Grade, Major
from app.services.validation import validate_major_code


async def resolve_book_scope(
    session: AsyncSession, *, book_id: int, grade_number: int, major_code: str | None
) -> tuple[Book, Grade, str | None]:
    """Resolve a book while strictly checking the caller's grade and major."""
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="book not found")
    grade = await session.get(Grade, book.grade_id)
    if grade is None or grade.number != grade_number:
        raise HTTPException(status_code=422, detail="book does not belong to the selected grade")

    major_error = validate_major_code(grade.has_major, major_code)
    if major_error:
        raise HTTPException(status_code=422, detail=major_error)

    book_major = await session.get(Major, book.major_id) if book.major_id is not None else None
    expected_major = book_major.code if book_major is not None else None
    if major_code != expected_major:
        raise HTTPException(status_code=422, detail="book does not belong to the selected major")
    return book, grade, expected_major
