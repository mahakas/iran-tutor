"""Admin API: book upload + background ingestion, status, preview, manual fix."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.curriculum import Book, BookPage, Grade, Major
from app.services.ingestion_service import UPLOAD_DIR, STORAGE_DIR, ingest_book_pages, model_tag, pdf_page_count
from app.services.preview import render_single_preview
from app.services.validation import validate_major_code

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
MAX_PDF_BYTES = 100 * 1024 * 1024


async def _run_ingest_background(
    *,
    book_id: int,
    pdf_path: Path,
    grade_number: int,
    major_code: str | None,
    book_title: str,
    start_page: int,
    end_page: int,
    model_primary: str,
    model_escalation: str | None,
    escalate_figures: bool,
) -> None:
    try:
        await ingest_book_pages(
            pdf_path=pdf_path,
            book_id=book_id,
            grade_number=grade_number,
            major_code=major_code,
            book_title=book_title,
            start_page=start_page,
            end_page=end_page,
            model_primary=model_primary,
            model_escalation=model_escalation,
            escalate_figures=escalate_figures,
            use_db=True,
        )
    except Exception:  # noqa: BLE001
        async with async_session_factory() as session:
            book = await session.get(Book, book_id)
            if book is not None:
                book.status = "failed"
                await session.commit()


@router.post("/books/upload-and-ingest")
async def upload_and_ingest(
    background_tasks: BackgroundTasks,
    pdf_file: UploadFile = File(...),
    grade_number: int = Form(...),
    major_code: str | None = Form(None),
    book_title: str = Form(...),
    start_page: int = Form(...),
    end_page: int = Form(...),
) -> dict[str, object]:
    settings = get_settings()

    if start_page < 1 or end_page < start_page:
        raise HTTPException(status_code=422, detail="invalid page range")

    async with async_session_factory() as session:
        grade = await session.scalar(select(Grade).where(Grade.number == grade_number))
        if grade is None:
            raise HTTPException(status_code=404, detail=f"grade {grade_number} not found")

        error = validate_major_code(grade.has_major, major_code)
        if error:
            raise HTTPException(status_code=422, detail=error)

        major_id = None
        if grade.has_major:
            major = await session.scalar(select(Major).where(Major.code == major_code))
            if major is None:
                raise HTTPException(status_code=404, detail=f"major '{major_code}' not found")
            major_id = major.id

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(pdf_file.filename or "upload.pdf").suffix or ".pdf"
        dest = UPLOAD_DIR / f"{uuid4().hex}{suffix}"
        pdf_bytes = await pdf_file.read(MAX_PDF_BYTES + 1)
        if not pdf_bytes:
            raise HTTPException(status_code=422, detail="uploaded PDF file is empty")
        if len(pdf_bytes) > MAX_PDF_BYTES:
            raise HTTPException(status_code=413, detail="PDF file exceeds 100 MiB limit")
        dest.write_bytes(pdf_bytes)
        try:
            page_count = pdf_page_count(dest)
        except Exception as exc:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail="uploaded file is not a valid PDF") from exc
        if end_page > page_count:
            dest.unlink(missing_ok=True)
            raise HTTPException(
                status_code=422,
                detail=f"page range ends at {end_page}, but the PDF contains only {page_count} pages",
            )

        book = Book(
            title=book_title,
            grade_id=grade.id,
            major_id=major_id,
            pdf_file_path=str(dest),
            total_pdf_pages=end_page - start_page + 1,
            status="ingesting",
        )
        session.add(book)
        await session.commit()
        await session.refresh(book)
        book_id = book.id

    background_tasks.add_task(
        _run_ingest_background,
        book_id=book_id,
        pdf_path=dest,
        grade_number=grade_number,
        major_code=major_code,
        book_title=book_title,
        start_page=start_page,
        end_page=end_page,
        model_primary=settings.vision_model_primary,
        model_escalation=settings.vision_model_escalation,
        escalate_figures=settings.escalate_figures,
    )
    return {"book_id": book_id, "status": "ingesting"}


@router.get("/books/{book_id}/status")
async def book_status(book_id: int) -> dict[str, object]:
    async with async_session_factory() as session:
        book = await session.get(Book, book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="book not found")
        rows = (
            await session.execute(
                select(BookPage.status, func.count())
                .where(BookPage.book_id == book_id)
                .group_by(BookPage.status)
            )
        ).all()
        counts = {status.value if hasattr(status, "value") else str(status): count for status, count in rows}
        return {
            "id": book.id,
            "title": book.title,
            "grade_id": book.grade_id,
            "major_id": book.major_id,
            "total_pdf_pages": book.total_pdf_pages,
            "status": book.status.value if hasattr(book.status, "value") else book.status,
            "pages": counts,
        }


class PageFixBody(BaseModel):
    markdown_content: str | None = None
    printed_page_number: int | None = None
    chapter_number: int | None = None
    chapter_title: str | None = None


@router.put("/books/{book_id}/pages/{idx}")
async def fix_page(book_id: int, idx: int, body: PageFixBody) -> dict[str, object]:
    async with async_session_factory() as session:
        page = await session.scalar(
            select(BookPage).where(BookPage.book_id == book_id, BookPage.pdf_page_index == idx)
        )
        if page is None:
            raise HTTPException(status_code=404, detail="page not found")

        if body.markdown_content is not None:
            page.markdown_content = body.markdown_content
        if body.printed_page_number is not None:
            page.printed_page_number = body.printed_page_number
        if body.chapter_number is not None:
            page.chapter_number = body.chapter_number
        if body.chapter_title is not None:
            page.chapter_title = body.chapter_title

        page.status = "done"
        page.edited_by_human = True
        page.error_message = None
        await session.commit()
        return {"book_id": book_id, "pdf_page_index": idx, "status": "done", "edited_by_human": True}


PREVIEW_STATUSES = ("all", "done", "failed", "needs_review", "pending")


@router.get("/books/{book_id}/preview", response_class=HTMLResponse)
async def book_preview(
    book_id: int,
    status: str | None = Query(None),
    page_from: int | None = Query(None, ge=1),
    page_to: int | None = Query(None, ge=1),
) -> str:
    if status is not None and status not in PREVIEW_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid status filter; allowed: {', '.join(PREVIEW_STATUSES)}",
        )
    if page_from is not None and page_to is not None and page_to < page_from:
        raise HTTPException(status_code=422, detail="invalid page range")

    async with async_session_factory() as session:
        query = select(BookPage).where(BookPage.book_id == book_id)
        if status and status != "all":
            query = query.where(BookPage.status == status)
        if page_from is not None:
            query = query.where(BookPage.pdf_page_index >= page_from)
        if page_to is not None:
            query = query.where(BookPage.pdf_page_index <= page_to)
        rows = (await session.scalars(query.order_by(BookPage.pdf_page_index))).all()
        if not rows:
            raise HTTPException(status_code=404, detail="no pages match the filter")

        model_name = rows[0].extraction_model or "model"
        tag = model_tag(model_name)
        pages = []
        for row in rows:
            pages.append(
                {
                    "pdf_page_index": row.pdf_page_index,
                    "image_path": row.page_image_path,
                    "printed_page_number": row.printed_page_number,
                    "chapter_number": row.chapter_number,
                    "chapter_title": row.chapter_title,
                    "status": row.status.value if hasattr(row.status, "value") else row.status,
                    "warnings": row.warnings,
                    "markdown": row.markdown_content,
                    "visual_elements": row.visual_elements,
                    "model": row.extraction_model,
                    "edited_by_human": bool(row.edited_by_human),
                }
            )
        out_path = STORAGE_DIR / "books" / str(book_id) / f"preview_{tag}.html"
    rendered = render_single_preview(book_id, tag, pages, out_path)
    return rendered.read_text(encoding="utf-8")
