"""Phase 5 Immersive Reader: TOC, page detail, and grounded assist actions.

Pages are served only for ready books and only to students with the
`immersive_reader` capability. Assist actions run through `capability_runtime`
with textbook strictness and cite the exact page the student is viewing.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.services import kb_ingestion_service
from app.services.capability_runtime import run_capability_text
from app.services.curriculum_access import is_student_visible_book

IMMERSIVE_CAPABILITY = "immersive_reader"
ASSIST_INSTRUCTIONS = {
    "summarize": "این بخش از کتاب درسی را در چند نکتهٔ کوتاه خلاصه کن.",
    "explain": "مفهوم اصلی این بخش از کتاب درسی را ساده و گام‌به‌گام توضیح بده.",
}


async def _ready_book(session: AsyncSession, book_id: int) -> Book:
    book = await session.get(Book, book_id)
    if not is_student_visible_book(book):
        raise HTTPException(status_code=404, detail="کتاب آماده‌ای با این شناسه یافت نشد.")
    return book


async def book_overview(session: AsyncSession, book_id: int) -> dict[str, Any]:
    book = await _ready_book(session, book_id)
    pages = (
        await session.scalars(
            select(BookPage)
            .where(BookPage.book_id == book_id, BookPage.status == PageStatus.done)
            .order_by(BookPage.pdf_page_index.asc())
        )
    ).all()
    chapters: dict[int, dict[str, Any]] = {}
    for page in pages:
        if page.chapter_number is None:
            continue
        entry = chapters.setdefault(
            page.chapter_number,
            {
                "chapter_number": page.chapter_number,
                "chapter_title": page.chapter_title or f"فصل {page.chapter_number}",
                "page_start": page.pdf_page_index,
                "page_end": page.pdf_page_index,
                "printed_start": page.printed_page_number,
                "printed_end": page.printed_page_number,
            },
        )
        entry["page_end"] = page.pdf_page_index
        if page.printed_page_number is not None:
            entry["printed_end"] = page.printed_page_number
    grade = await session.get(Grade, book.grade_id)
    major = await session.get(Major, book.major_id) if book.major_id else None
    return {
        "id": book.id,
        "title": book.title,
        "grade_number": grade.number if grade else None,
        "major_code": major.code if major else "general",
        "page_count": len(pages),
        "chapters": list(chapters.values()),
        "pages": [
            {
                "pdf_page_index": page.pdf_page_index,
                "printed_page_number": page.printed_page_number,
                "chapter_number": page.chapter_number,
                "chapter_title": page.chapter_title,
            }
            for page in pages
        ],
    }


def citation_for_page(book: Book, page: BookPage) -> dict[str, Any]:
    chapter = page.chapter_title or (f"فصل {page.chapter_number}" if page.chapter_number else "فصل نامشخص")
    printed = f"صفحه چاپی {page.printed_page_number}" if page.printed_page_number is not None else "صفحه نامشخص"
    return {
        "book_id": book.id,
        "book_title": book.title,
        "chapter_number": page.chapter_number,
        "chapter_title": page.chapter_title,
        "pdf_page_index": page.pdf_page_index,
        "printed_page_number": page.printed_page_number,
        "citation": f"{book.title}، {chapter}، {printed}",
    }


async def page_detail(session: AsyncSession, book_id: int, pdf_page_index: int) -> dict[str, Any]:
    book = await _ready_book(session, book_id)
    page = await session.scalar(
        select(BookPage).where(BookPage.book_id == book_id, BookPage.pdf_page_index == pdf_page_index)
    )
    if page is None or page.status != PageStatus.done:
        raise HTTPException(status_code=404, detail="صفحه یافت نشد.")
    figures = await kb_ingestion_service.list_figures(session, book_id=book_id, page_index=pdf_page_index)
    return {
        **citation_for_page(book, page),
        "markdown_content": page.markdown_content,
        "figures": [kb_ingestion_service.serialize_figure(figure) for figure in figures],
    }


async def page_image_path(session: AsyncSession, book_id: int, pdf_page_index: int) -> str:
    await _ready_book(session, book_id)
    page = await session.scalar(
        select(BookPage).where(BookPage.book_id == book_id, BookPage.pdf_page_index == pdf_page_index)
    )
    if page is None or page.status != PageStatus.done or not page.page_image_path:
        raise HTTPException(status_code=404, detail="تصویر صفحه موجود نیست.")
    return page.page_image_path


async def assist(
    session: AsyncSession,
    user: User,
    *,
    book_id: int,
    action: str,
    pdf_page_index: int,
    selection: str | None = None,
) -> dict[str, Any]:
    if action not in ASSIST_INSTRUCTIONS:
        raise HTTPException(status_code=422, detail="اقدام نامعتبر است.")
    book = await _ready_book(session, book_id)
    page = await session.scalar(
        select(BookPage).where(BookPage.book_id == book_id, BookPage.pdf_page_index == pdf_page_index)
    )
    if page is None or page.status != PageStatus.done:
        raise HTTPException(status_code=404, detail="صفحه یافت نشد.")
    context = (selection or "").strip() or (page.markdown_content or "").strip()
    if not context:
        raise HTTPException(status_code=409, detail="متنی برای این صفحه ثبت نشده است.")
    citation = citation_for_page(book, page)
    try:
        result, _blocks, _skill = await run_capability_text(
            session=session,
            capability_key=IMMERSIVE_CAPABILITY,
            feature_key=IMMERSIVE_CAPABILITY,
            user_text=f"{ASSIST_INSTRUCTIONS[action]}\n\nمتن کتاب:\n{context[:6000]}",
            user_id=user.id,
            book_id=book_id,
            textbook_strict=True,
            citations=[citation],
            rag_hit_count=1,
            user=user,
            enforce=True,
        )
    except Exception:
        # Persist the gateway audit row even when the call fails (glass box), then re-raise.
        await session.commit()
        raise
    await session.commit()
    return {"answer": result.content, "citation": citation, "audit_id": result.audit_id, "action": action}
