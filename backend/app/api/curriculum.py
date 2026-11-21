"""Read-only curriculum selectors for student and admin clients."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.services.search_normalize import search_key, sql_search_key
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


@router.get("/search")
async def search_curriculum(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=10, ge=1, le=25),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    term = q.strip()
    pattern = f"%{search_key(term)}%" if term else None

    book_stmt = (
        select(Book, Grade.number, Grade.title, Major.code, Major.title)
        .join(Grade, Book.grade_id == Grade.id)
        .outerjoin(Major, Book.major_id == Major.id)
        .where(Book.status == BookStatus.ready)
    )
    if pattern is not None:
        book_stmt = book_stmt.where(
            or_(sql_search_key(Book.title).like(pattern), sql_search_key(Grade.title).like(pattern), sql_search_key(Major.title).like(pattern))
        )
    book_rows = (await session.execute(book_stmt.order_by(Book.title).limit(limit))).all()

    topic_stmt = (
        select(BookPage, Book.title, Grade.number, Major.code)
        .join(Book, BookPage.book_id == Book.id)
        .join(Grade, Book.grade_id == Grade.id)
        .outerjoin(Major, Book.major_id == Major.id)
        .where(Book.status == BookStatus.ready, BookPage.status == PageStatus.done)
    )
    if pattern is not None:
        topic_stmt = topic_stmt.where(
            or_(
                sql_search_key(BookPage.chapter_title).like(pattern),
                sql_search_key(BookPage.markdown_content).like(pattern),
                sql_search_key(Book.title).like(pattern),
            )
        )
    topic_rows = (
        await session.execute(topic_stmt.order_by(Book.id.desc(), BookPage.pdf_page_index.asc()).limit(limit))
    ).all()

    return {
        "query": term,
        "books": [
            {
                "id": book.id,
                "title": book.title,
                "grade_number": grade_num,
                "grade_title": grade_title,
                "major_code": major_code or "general",
                "major_title": major_title,
            }
            for book, grade_num, grade_title, major_code, major_title in book_rows
        ],
        "topics": [
            {
                "book_id": page.book_id,
                "book_title": book_title,
                "grade_number": grade_num,
                "major_code": major_code or "general",
                "chapter_number": page.chapter_number,
                "chapter_title": page.chapter_title,
                "printed_page_number": page.printed_page_number,
                "pdf_page_index": page.pdf_page_index,
            }
            for page, book_title, grade_num, major_code in topic_rows
        ],
    }
