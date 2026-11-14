"""Read-only curriculum selectors for student and admin clients."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.curriculum import Book, BookStatus, Grade, Major
from app.services.validation import validate_major_code

router = APIRouter(prefix="/api/v1/curriculum", tags=["curriculum"])


@router.get("/grades")
async def list_grades(session: AsyncSession = Depends(get_session)) -> list[dict[str, object]]:
    grades = (await session.scalars(select(Grade).order_by(Grade.number))).all()
    return [
        {"number": grade.number, "title": grade.title, "has_major": grade.has_major}
        for grade in grades
    ]


@router.get("/majors")
async def list_majors(session: AsyncSession = Depends(get_session)) -> list[dict[str, str]]:
    majors = (await session.scalars(select(Major).order_by(Major.id))).all()
    return [{"code": major.code, "title": major.title} for major in majors]


@router.get("/books")
async def list_books(
    grade_number: int = Query(ge=1, le=12),
    major_code: str | None = Query(None, max_length=64),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    grade = await session.scalar(select(Grade).where(Grade.number == grade_number))
    if grade is None:
        raise HTTPException(status_code=404, detail="grade not found")
    error = validate_major_code(grade.has_major, major_code)
    if error:
        raise HTTPException(status_code=422, detail=error)

    selected_major_id = None
    if grade.has_major:
        major = await session.scalar(select(Major).where(Major.code == major_code))
        if major is None:
            raise HTTPException(status_code=404, detail="major not found")
        selected_major_id = major.id

    books = (
        await session.scalars(
            select(Book)
            .where(
                Book.grade_id == grade.id,
                Book.major_id == selected_major_id,
                Book.status == BookStatus.ready,
            )
            .order_by(Book.title)
        )
    ).all()
    return [
        {
            "id": book.id,
            "title": book.title,
            "grade_number": grade_number,
            "major_code": major_code or "general",
            "status": book.status.value,
        }
        for book in books
    ]
