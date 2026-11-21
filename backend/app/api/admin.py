"""Admin API: password-protected book upload + ingestion, status, preview, manual fix."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import logging
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, or_, select, text as sql_text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_base_settings, get_settings
from app.core.runtime_config import (
    ALL_RUNTIME_FIELDS,
    RESET_SECTION_FIELDS,
    apply_runtime_patch,
    get_runtime_overrides,
    normalize_persisted_overrides,
    refresh_runtime_clients,
    serialize_admin_settings,
    set_runtime_overrides,
)
from app.db.session import async_session_factory
from app.models.auth import PaymentTransaction, Plan, TokenUsageLog, User, UserFile, UserSession
from app.models.chat import ChatSession
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.models.exam import ExamSession
from app.models.governance import AiAuditLog, AiProvider, FeatureModelRoute
from app.services.upload_guard import verify_extension, verify_pdf
from app.services.ai_provider_service import (
    PROVIDER_CAPABILITIES,
    PROVIDER_TYPES,
)
from app.db.session import get_session
from app.services.document_parser import detect_document_format, parse_structured_document
from app.services.account_service import (
    default_preferences,
    get_user_storage_quota_bytes,
    merge_preferences,
    normalize_preferences,
)
from app.services.auth_billing_service import (
    apply_plan_to_user,
    calculate_token_cost_toman,
    get_or_init_billing_settings,
    get_or_init_plans,
    get_user_today_tokens,
    normalize_iranian_phone,
    serialize_plan,
    serialize_user,
    utc_iso,
)
from app.services.ingestion_service import (
    STORAGE_DIR,
    UPLOAD_DIR,
    _export_assets,
    build_export_pages,
    ingest_book_pages,
    model_tag,
    pdf_page_count,
)
from app.services.preview import render_single_preview
from app.services.retrieval_service import index_book
from app.services.sms_provider import get_sms_provider
from app.services.validation import validate_major_code

ADMIN_COOKIE_NAME = "iran_tutor_admin"
MAX_PDF_BYTES = 100 * 1024 * 1024
logger = logging.getLogger(__name__)


def _admin_signing_key() -> bytes:
    settings = get_settings()
    base = get_base_settings()
    overrides = get_runtime_overrides()
    stable_llm_key = (
        base.llm_api_key if "llm_api_key" in overrides else getattr(settings, "llm_api_key", "")
    )
    material = (
        f"iran-tutor-admin-v2:{settings.admin_username}:{settings.admin_password}:{stable_llm_key}"
    ).encode("utf-8")
    return hashlib.sha256(material).digest()


def create_admin_session_token(*, ttl_seconds: int | None = None) -> str:
    settings = get_settings()
    ttl = ttl_seconds if ttl_seconds is not None else settings.admin_session_ttl_seconds
    expires_at = int(time.time()) + ttl
    nonce = secrets.token_hex(16)
    payload = f"{expires_at}.{nonce}"
    signature = hmac.new(_admin_signing_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_admin_session_token(token: str | None) -> bool:
    if not token or token.count(".") != 2:
        return False
    expires_raw, nonce, signature = token.split(".", 2)
    if not expires_raw.isdigit() or not nonce or not signature:
        return False
    if int(expires_raw) <= int(time.time()):
        return False
    expected = hmac.new(
        _admin_signing_key(),
        f"{expires_raw}.{nonce}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def _is_admin_authenticated(request: Request) -> bool:
    settings = get_settings()
    if not settings.admin_username or not settings.admin_password:
        return False

    token_header = request.headers.get("x-admin-token", "").strip()
    if token_header and verify_admin_session_token(token_header):
        return True

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        bearer_token = auth_header[7:].strip()
        if verify_admin_session_token(bearer_token):
            return True

    header_user = request.headers.get("x-admin-username")
    header_pw = request.headers.get("x-admin-password")
    if (
        header_user
        and header_pw
        and hmac.compare_digest(header_user, settings.admin_username)
        and hmac.compare_digest(header_pw, settings.admin_password)
    ):
        return True

    return verify_admin_session_token(request.cookies.get(ADMIN_COOKIE_NAME))


async def _resolve_rbac_admin(request: Request, session: AsyncSession):
    """Return the user behind an admin-role session token, or `None`."""
    from app.api.rbac_deps import normalize_role
    from app.services.rbac import get_optional_user

    try:
        user = await get_optional_user(request, session)
    except Exception:  # noqa: BLE001 - the legacy HMAC session is the fallback path
        logger.exception("admin.auth.rbac_lookup_failed")
        return None
    if user is None or not user.is_active:
        return None
    if normalize_role(user.role) != "admin":
        return None
    return user


async def require_admin(
    request: Request, session: AsyncSession = Depends(get_session)
) -> None:
    """Guard every `/api/v1/admin/*` route (Phase 1, Rule 2).

    Accepts either the legacy admin session (shared admin password, cookie /
    X-Admin-Token) or a real user session whose role is `admin`.
    Unauthenticated -> 401, authenticated but not an admin -> 403.
    """
    if _is_admin_authenticated(request):
        request.state.admin_identity = {"kind": "admin_session", "user_id": None, "role": "admin"}
        return

    user = await _resolve_rbac_admin(request, session)
    if user is not None:
        request.state.admin_identity = {
            "kind": "user_session",
            "user_id": user.id,
            "role": "admin",
        }
        request.state.current_user = user
        return

    from app.api.rbac_deps import normalize_role
    from app.services.rbac import get_optional_user

    try:
        candidate = await get_optional_user(request, session)
    except Exception:  # noqa: BLE001
        candidate = None

    logger.warning(
        "Admin auth failed for %s; header_keys=%s has_cookie=%s role=%s",
        request.url.path,
        sorted(k for k in request.headers.keys() if k in {"authorization", "x-admin-token", "cookie"}),
        ADMIN_COOKIE_NAME in request.cookies,
        normalize_role(candidate.role) if candidate is not None else None,
    )
    if candidate is not None:
        raise HTTPException(
            status_code=403,
            detail="این بخش فقط برای مدیران سامانه در دسترس است.",
        )
    raise HTTPException(status_code=401, detail="احراز هویت مدیر لازم است.")


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
protected_router = APIRouter(dependencies=[Depends(require_admin)])


class AdminLoginBody(BaseModel):
    username: str
    password: str


@router.get("/auth/session")
async def get_admin_session(request: Request) -> dict[str, object]:
    authed = _is_admin_authenticated(request)
    return {
        "authenticated": authed,
        "username": get_settings().admin_username if authed else None,
    }


@router.post("/auth/login")
async def admin_login(body: AdminLoginBody, request: Request, response: Response) -> dict[str, object]:
    settings = get_settings()
    valid_user = bool(settings.admin_username) and hmac.compare_digest(
        body.username.strip(), settings.admin_username
    )
    valid_pass = bool(settings.admin_password) and hmac.compare_digest(
        body.password, settings.admin_password
    )
    if not (valid_user and valid_pass):
        raise HTTPException(status_code=401, detail="نام کاربری یا رمز عبور مدیر نادرست است.")
    token = create_admin_session_token()
    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
    )
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=token,
        max_age=settings.admin_session_ttl_seconds,
        httponly=True,
        samesite="none" if is_https else "lax",
        secure=is_https,
        path="/",
    )
    return {
        "authenticated": True,
        "token": token,
        "username": settings.admin_username,
    }


@router.post("/auth/logout")
async def admin_logout(request: Request, response: Response) -> dict[str, bool]:
    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
    )
    response.delete_cookie(
        key=ADMIN_COOKIE_NAME,
        path="/",
        samesite="none" if is_https else "lax",
        secure=is_https,
    )
    return {"authenticated": False}


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
    job_id: str | None = None,
) -> None:
    # Phase 2: when a tracked KB job exists, the job runner owns execution,
    # progress counters and book status (see kb_ingestion_service).
    if job_id is not None:
        from app.services import kb_ingestion_service

        await kb_ingestion_service.run_ingestion_job(job_id)
        return
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


@protected_router.post("/books/upload-and-ingest")
async def upload_and_ingest(
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(None),
    pdf_file: UploadFile | None = File(None),
    grade_number: int = Form(...),
    major_code: str | None = Form(None),
    book_title: str = Form(...),
    start_page: int = Form(1),
    end_page: int | None = Form(None),
) -> dict[str, object]:
    settings = get_settings()
    upload = file or pdf_file
    if upload is None:
        raise HTTPException(status_code=422, detail="لطفاً یک فایل کتاب انتخاب کنید.")

    try:
        doc_format = detect_document_format(upload.filename, upload.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if doc_format == "pdf":
        if end_page is None or start_page < 1 or end_page < start_page:
            raise HTTPException(status_code=422, detail="invalid page range")
    elif start_page < 1 or (end_page is not None and end_page < start_page):
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

        raw_bytes = await upload.read(MAX_PDF_BYTES + 1)
        if not raw_bytes:
            raise HTTPException(status_code=422, detail="uploaded file is empty")
        if len(raw_bytes) > MAX_PDF_BYTES:
            raise HTTPException(status_code=413, detail="file exceeds 100 MiB limit")

        if doc_format == "pdf":
            verify_pdf(raw_bytes)
        else:
            verify_extension(upload.filename or "", raw_bytes)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        default_ext = ".pdf" if doc_format == "pdf" else f".{doc_format if doc_format != 'markdown' else 'md'}"
        suffix = default_ext
        dest = UPLOAD_DIR / f"{uuid4().hex}{suffix}"

        if doc_format == "pdf":
            assert end_page is not None
            dest.write_bytes(raw_bytes)
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

            from app.services import kb_ingestion_service

            job = await kb_ingestion_service.create_ingestion_job(
                session, book_id=book_id, start_page=start_page, end_page=end_page
            )
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
                job_id=job.id,
            )
            return {
                "book_id": book_id,
                "status": "ingesting",
                "format": "pdf",
                "total_pages": end_page - start_page + 1,
                "job_id": job.id,
            }

        # Structured text/document upload (.md, .json, .html)
        try:
            parsed_pages = parse_structured_document(raw_bytes, fmt=doc_format)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if end_page is not None:
            if end_page > len(parsed_pages):
                raise HTTPException(
                    status_code=422,
                    detail=f"page range ends at {end_page}, but the file contains only {len(parsed_pages)} sections/pages",
                )
            selected_pages = parsed_pages[start_page - 1 : end_page]
        else:
            if start_page > len(parsed_pages):
                raise HTTPException(
                    status_code=422,
                    detail=f"start page {start_page} exceeds {len(parsed_pages)} sections/pages",
                )
            selected_pages = parsed_pages[start_page - 1 :]

        dest.write_bytes(raw_bytes)
        model_label = f"structured-{doc_format}"
        book = Book(
            title=book_title,
            grade_id=grade.id,
            major_id=major_id,
            pdf_file_path=str(dest),
            total_pdf_pages=len(selected_pages),
            status="ready",
        )
        session.add(book)
        await session.flush()
        book_id = book.id

        page_rows: list[BookPage] = []
        status_counts: dict[str, int] = {}
        for seq_idx, parsed in enumerate(selected_pages, start=1):
            page_idx = parsed.page_index if end_page is None and start_page == 1 else seq_idx
            page_status = PageStatus.needs_review if parsed.warnings else PageStatus.done
            status_key = page_status.value
            status_counts[status_key] = status_counts.get(status_key, 0) + 1
            row = BookPage(
                book_id=book_id,
                pdf_page_index=page_idx,
                printed_page_number=parsed.printed_page_number,
                chapter_number=parsed.chapter_number,
                chapter_title=parsed.chapter_title,
                markdown_content=parsed.markdown_content,
                visual_elements=parsed.visual_elements,
                page_image_path="",
                status=page_status,
                warnings=parsed.warnings,
                extraction_model=model_label,
                edited_by_human=False,
            )
            session.add(row)
            page_rows.append(row)

        await session.commit()

        try:
            _export_assets(book_id, build_export_pages(page_rows))
        except Exception as exc:  # noqa: BLE001
            logger.warning("structured book asset export failed for %s: %s", book_id, exc)

        return {
            "book_id": book_id,
            "status": "ready",
            "format": doc_format,
            "total_pages": len(selected_pages),
            "pages": status_counts,
        }


@protected_router.get("/books")
async def list_admin_books() -> list[dict[str, object]]:
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(Book, Grade.number, Major.code)
                .join(Grade, Book.grade_id == Grade.id)
                .outerjoin(Major, Book.major_id == Major.id)
                .order_by(Book.id.desc())
            )
        ).all()
        page_rows = (
            await session.execute(
                select(BookPage.book_id, BookPage.status, func.count()).group_by(
                    BookPage.book_id, BookPage.status
                )
            )
        ).all()
        counts_by_book: dict[int, dict[str, int]] = {}
        for book_id, status, count in page_rows:
            key = status.value if hasattr(status, "value") else str(status)
            counts_by_book.setdefault(book_id, {})[key] = count
        return [
            {
                "id": book.id,
                "title": book.title,
                "grade_id": book.grade_id,
                "grade_number": grade_number,
                "major_id": book.major_id,
                "major_code": major_code,
                "total_pdf_pages": book.total_pdf_pages,
                "status": book.status.value if hasattr(book.status, "value") else book.status,
                "pages": counts_by_book.get(book.id, {}),
            }
            for book, grade_number, major_code in rows
        ]


@protected_router.get("/books/{book_id}/status")
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


@protected_router.get("/books/{book_id}/pages")
async def list_book_pages(book_id: int) -> list[dict[str, object]]:
    async with async_session_factory() as session:
        book = await session.get(Book, book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="book not found")
        rows = (
            await session.scalars(
                select(BookPage)
                .where(BookPage.book_id == book_id)
                .order_by(BookPage.pdf_page_index)
            )
        ).all()
        return [
            {
                "pdf_page_index": row.pdf_page_index,
                "printed_page_number": row.printed_page_number,
                "chapter_number": row.chapter_number,
                "chapter_title": row.chapter_title,
                "status": row.status.value if hasattr(row.status, "value") else row.status,
                "warnings": row.warnings or [],
                "markdown_content": row.markdown_content or "",
                "original_markdown_content": getattr(row, "original_markdown_content", None),
                "visual_elements": row.visual_elements or [],
                "extraction_model": row.extraction_model,
                "edited_by_human": bool(row.edited_by_human),
                "error_message": row.error_message,
                "image_url": (
                    f"/api/v1/admin/books/{book_id}/pages/{row.pdf_page_index}/image"
                    if row.page_image_path
                    else None
                ),
            }
            for row in rows
        ]


@protected_router.get("/books/{book_id}/pages/{idx}/image")
async def get_page_image(book_id: int, idx: int) -> FileResponse:
    async with async_session_factory() as session:
        page = await session.scalar(
            select(BookPage).where(BookPage.book_id == book_id, BookPage.pdf_page_index == idx)
        )
        if page is None or not page.page_image_path:
            raise HTTPException(status_code=404, detail="page image not found")
        image_path = Path(page.page_image_path)
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="page image file missing")
    return FileResponse(image_path, media_type="image/png")


class PageFixBody(BaseModel):
    markdown_content: str | None = None
    printed_page_number: int | None = None
    chapter_number: int | None = None
    chapter_title: str | None = None


@protected_router.put("/books/{book_id}/pages/{idx}")
async def fix_page(book_id: int, idx: int, body: PageFixBody) -> dict[str, object]:
    async with async_session_factory() as session:
        page = await session.scalar(
            select(BookPage).where(BookPage.book_id == book_id, BookPage.pdf_page_index == idx)
        )
        if page is None:
            raise HTTPException(status_code=404, detail="page not found")

        fields = body.model_fields_set
        if "markdown_content" in fields and body.markdown_content is not None:
            if getattr(page, "original_markdown_content", None) is None:
                page.original_markdown_content = page.markdown_content or ""
            page.markdown_content = body.markdown_content
        if "printed_page_number" in fields:
            page.printed_page_number = body.printed_page_number
        if "chapter_number" in fields:
            page.chapter_number = body.chapter_number
        if "chapter_title" in fields:
            page.chapter_title = body.chapter_title

        page.status = "done"
        page.edited_by_human = True
        page.error_message = None
        page.warnings = []
        await session.commit()

        rows = list(
            (
                await session.scalars(
                    select(BookPage)
                    .where(BookPage.book_id == book_id)
                    .order_by(BookPage.pdf_page_index)
                )
            ).all()
        )
        if rows:
            _export_assets(book_id, build_export_pages(rows))
        return {
            "book_id": book_id,
            "pdf_page_index": idx,
            "status": "done",
            "edited_by_human": True,
            "original_markdown_content": getattr(page, "original_markdown_content", None),
        }


PREVIEW_STATUSES = ("all", "done", "failed", "needs_review", "pending")


@protected_router.get("/books/{book_id}/preview", response_class=HTMLResponse)
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


class BillingSettingsUpdateBody(BaseModel):
    token_price_per_1k_toman: int = Field(ge=1, le=100_000_000)
    starter_tokens: int = Field(ge=0, le=100_000_000)
    starter_duration_days: int = Field(ge=1, le=3650)
    starter_storage_bytes: int | None = Field(default=None, ge=1_048_576, le=10_737_418_240)


class PlanUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    price_toman: int | None = Field(default=None, ge=0, le=1_000_000_000)
    token_quota: int | None = Field(default=None, ge=1, le=1_000_000_000)
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    storage_quota_bytes: int | None = Field(default=None, ge=1_048_576, le=107_374_182_400)
    is_active: bool | None = None


class AdminUserUpdateBody(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    plan_code: str | None = Field(default=None, min_length=1, max_length=32)
    apply_plan_defaults: bool = True
    tokens_remaining: int | None = Field(default=None, ge=0, le=1_000_000_000)
    add_tokens: int | None = Field(default=None, ge=-1_000_000_000, le=1_000_000_000)
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    is_active: bool | None = None


@protected_router.get("/billing")
async def get_admin_billing() -> dict[str, object]:
    async with async_session_factory() as session:
        billing = await get_or_init_billing_settings(session)
        plans = await get_or_init_plans(session)
        await session.commit()
        return {
            "settings": {
                "token_price_per_1k_toman": billing.token_price_per_1k_toman,
                "starter_tokens": billing.starter_tokens,
                "starter_duration_days": billing.starter_duration_days,
                "starter_storage_bytes": billing.starter_storage_bytes,
            },
            "plans": [serialize_plan(plan) for plan in plans],
        }


@protected_router.put("/billing/settings")
async def update_admin_billing_settings(body: BillingSettingsUpdateBody) -> dict[str, object]:
    async with async_session_factory() as session:
        billing = await get_or_init_billing_settings(session)
        billing.token_price_per_1k_toman = body.token_price_per_1k_toman
        billing.starter_tokens = body.starter_tokens
        billing.starter_duration_days = body.starter_duration_days
        if body.starter_storage_bytes is not None:
            billing.starter_storage_bytes = body.starter_storage_bytes
        await session.commit()
        await session.refresh(billing)
        return {
            "settings": {
                "token_price_per_1k_toman": billing.token_price_per_1k_toman,
                "starter_tokens": billing.starter_tokens,
                "starter_duration_days": billing.starter_duration_days,
                "starter_storage_bytes": billing.starter_storage_bytes,
            }
        }


@protected_router.put("/billing/plans/{plan_code}")
async def update_admin_plan(plan_code: str, body: PlanUpdateBody) -> dict[str, object]:
    async with async_session_factory() as session:
        await get_or_init_plans(session)
        plan = await session.scalar(select(Plan).where(Plan.code == plan_code.strip()))
        if plan is None:
            raise HTTPException(status_code=404, detail="پلن مورد نظر یافت نشد.")
        fields = body.model_fields_set
        if "name" in fields and body.name is not None:
            plan.name = body.name.strip()
        if "description" in fields and body.description is not None:
            plan.description = body.description.strip()
        if "price_toman" in fields and body.price_toman is not None:
            plan.price_toman = body.price_toman
        if "token_quota" in fields and body.token_quota is not None:
            plan.token_quota = body.token_quota
        if "duration_days" in fields and body.duration_days is not None:
            plan.duration_days = body.duration_days
        if "storage_quota_bytes" in fields and body.storage_quota_bytes is not None:
            plan.storage_quota_bytes = body.storage_quota_bytes
        if "is_active" in fields and body.is_active is not None:
            plan.is_active = body.is_active
        await session.commit()
        await session.refresh(plan)
        return {"plan": serialize_plan(plan)}


@protected_router.get("/users")
async def list_admin_users(
    q: str | None = Query(None, max_length=64),
    plan: str | None = Query(None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, object]:
    async with async_session_factory() as session:
        billing = await get_or_init_billing_settings(session)
        query = select(User).order_by(User.created_at.desc()).limit(limit)
        if q and q.strip():
            term = f"%{q.strip()}%"
            query = query.where(or_(User.phone_number.ilike(term), User.full_name.ilike(term)))
        if plan and plan.strip() and plan != "all":
            query = query.where(User.plan_code == plan.strip())

        users = list((await session.scalars(query)).all())
        start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_rows = (
            await session.execute(
                select(TokenUsageLog.user_id, func.coalesce(func.sum(TokenUsageLog.total_tokens), 0))
                .where(TokenUsageLog.created_at >= start_of_day)
                .group_by(TokenUsageLog.user_id)
            )
        ).all()
        today_by_user = {uid: int(total) for uid, total in today_rows}

        total_users = int(await session.scalar(select(func.count()).select_from(User)) or 0)
        active_users = int(
            await session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0
        )
        paid_users = int(
            await session.scalar(
                select(func.count()).select_from(User).where(User.plan_code.in_(["normal", "pro", "vip"]))
            )
            or 0
        )
        total_tokens_used = int(
            await session.scalar(select(func.coalesce(func.sum(User.tokens_used_total), 0))) or 0
        )
        total_revenue_toman = int(
            await session.scalar(
                select(func.coalesce(func.sum(PaymentTransaction.amount_toman), 0)).where(
                    PaymentTransaction.status == "paid",
                    PaymentTransaction.provider != "admin_grant",
                )
            )
            or 0
        )
        plans_list = await get_or_init_plans(session)
        plan_storage = {p.code: int(p.storage_quota_bytes) for p in plans_list}
        await session.commit()

        return {
            "summary": {
                "total_users": total_users,
                "active_users": active_users,
                "paid_users": paid_users,
                "total_tokens_used": total_tokens_used,
                "total_used_value_toman": calculate_token_cost_toman(
                    total_tokens_used, token_price_per_1k_toman=billing.token_price_per_1k_toman
                ),
                "total_revenue_toman": total_revenue_toman,
            },
            "users": [
                serialize_user(
                    u,
                    today_tokens=today_by_user.get(u.id, 0),
                    token_price_per_1k_toman=billing.token_price_per_1k_toman,
                    storage_quota_bytes=(
                        int(billing.starter_storage_bytes)
                        if u.plan_code == "trial"
                        else plan_storage.get(u.plan_code, int(billing.starter_storage_bytes))
                    ),
                )
                for u in users
            ],
        }


@protected_router.put("/users/{user_id}")
async def update_admin_user(user_id: str, body: AdminUserUpdateBody) -> dict[str, object]:
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="کاربر یافت نشد.")

        billing = await get_or_init_billing_settings(session)
        await get_or_init_plans(session)
        now = datetime.now(timezone.utc)
        fields = body.model_fields_set

        if "full_name" in fields:
            user.full_name = body.full_name.strip() if body.full_name and body.full_name.strip() else None
        if "is_active" in fields and body.is_active is not None:
            user.is_active = body.is_active

        if body.plan_code is not None:
            code = body.plan_code.strip()
            if code == "trial":
                if body.apply_plan_defaults:
                    apply_plan_to_user(
                        user,
                        plan_code="trial",
                        plan_name="هدیه ثبت‌نام",
                        tokens_granted=billing.starter_tokens,
                        duration_days=body.duration_days or billing.starter_duration_days,
                        carry_over_valid=False,
                        now=now,
                    )
                else:
                    user.plan_code = "trial"
                    user.plan_title = "هدیه ثبت‌نام"
            else:
                plan = await session.scalar(select(Plan).where(Plan.code == code))
                if plan is None:
                    raise HTTPException(status_code=404, detail="پلن انتخاب‌شده یافت نشد.")
                if body.apply_plan_defaults:
                    days = body.duration_days or plan.duration_days
                    apply_plan_to_user(
                        user,
                        plan_code=plan.code,
                        plan_name=plan.name,
                        tokens_granted=plan.token_quota,
                        duration_days=days,
                        carry_over_valid=True,
                        now=now,
                    )
                    session.add(
                        PaymentTransaction(
                            user_id=user.id,
                            plan_code=plan.code,
                            plan_name=plan.name,
                            amount_toman=0,
                            tokens_granted=plan.token_quota,
                            duration_days=days,
                            provider="admin_grant",
                            authority=f"ADMIN-{uuid4().hex[:10].upper()}",
                            ref_id="ADMIN",
                            status="paid",
                            paid_at=now,
                        )
                    )
                else:
                    user.plan_code = plan.code
                    user.plan_title = plan.name

        if body.tokens_remaining is not None:
            user.tokens_remaining = body.tokens_remaining
            if user.tokens_total < body.tokens_remaining:
                user.tokens_total = body.tokens_remaining

        if body.add_tokens is not None and body.add_tokens != 0:
            user.tokens_remaining = max(0, user.tokens_remaining + body.add_tokens)
            if body.add_tokens > 0:
                user.tokens_total = max(user.tokens_total, user.tokens_remaining)

        if body.duration_days is not None and body.plan_code is None:
            user.plan_expires_at = now + timedelta(days=body.duration_days)

        await session.commit()
        await session.refresh(user)
        today_tokens = await get_user_today_tokens(session, user.id)
        storage_quota = await get_user_storage_quota_bytes(session, user, billing)
        return {
            "user": serialize_user(
                user,
                today_tokens=today_tokens,
                token_price_per_1k_toman=billing.token_price_per_1k_toman,
                storage_quota_bytes=storage_quota,
                now=now,
            )
        }


@protected_router.get("/users/{user_id}/usage")
async def get_admin_user_usage(
    user_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, object]:
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="کاربر یافت نشد.")

        billing = await get_or_init_billing_settings(session)
        now = datetime.now(timezone.utc)
        today_tokens = await get_user_today_tokens(session, user.id)

        action_rows = (
            await session.execute(
                select(
                    TokenUsageLog.action,
                    func.count(TokenUsageLog.id),
                    func.coalesce(func.sum(TokenUsageLog.prompt_tokens), 0),
                    func.coalesce(func.sum(TokenUsageLog.completion_tokens), 0),
                    func.coalesce(func.sum(TokenUsageLog.total_tokens), 0),
                    func.coalesce(func.sum(TokenUsageLog.cost_toman), 0),
                )
                .where(TokenUsageLog.user_id == user.id)
                .group_by(TokenUsageLog.action)
                .order_by(func.coalesce(func.sum(TokenUsageLog.total_tokens), 0).desc())
            )
        ).all()

        cutoff = now - timedelta(days=days)
        daily_source_rows = (
            await session.execute(
                select(
                    TokenUsageLog.created_at,
                    TokenUsageLog.total_tokens,
                    TokenUsageLog.cost_toman,
                )
                .where(TokenUsageLog.user_id == user.id, TokenUsageLog.created_at >= cutoff)
                .order_by(TokenUsageLog.created_at.desc())
            )
        ).all()
        daily_buckets: dict[str, dict[str, int]] = {}
        for created_at, total_tok, cost_tm in daily_source_rows:
            dt = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=timezone.utc)
            date_key = dt.date().isoformat()
            bucket = daily_buckets.setdefault(
                date_key, {"requests": 0, "total_tokens": 0, "cost_toman": 0}
            )
            bucket["requests"] += 1
            bucket["total_tokens"] += int(total_tok or 0)
            bucket["cost_toman"] += int(cost_tm or 0)

        log_rows = (
            await session.execute(
                select(TokenUsageLog, Book.title)
                .outerjoin(Book, TokenUsageLog.book_id == Book.id)
                .where(TokenUsageLog.user_id == user.id)
                .order_by(TokenUsageLog.created_at.desc())
                .limit(limit)
            )
        ).all()

        payments = (
            await session.scalars(
                select(PaymentTransaction)
                .where(PaymentTransaction.user_id == user.id)
                .order_by(PaymentTransaction.created_at.desc())
                .limit(20)
            )
        ).all()

        storage_quota = await get_user_storage_quota_bytes(session, user, billing)
        return {
            "user": serialize_user(
                user,
                today_tokens=today_tokens,
                token_price_per_1k_toman=billing.token_price_per_1k_toman,
                storage_quota_bytes=storage_quota,
                now=now,
            ),
            "token_price_per_1k_toman": billing.token_price_per_1k_toman,
            "by_action": [
                {
                    "action": action,
                    "count": int(cnt or 0),
                    "prompt_tokens": int(p_tok or 0),
                    "completion_tokens": int(c_tok or 0),
                    "total_tokens": int(t_tok or 0),
                    "cost_toman": int(cost or 0),
                }
                for action, cnt, p_tok, c_tok, t_tok, cost in action_rows
            ],
            "daily": [
                {"date": date_key, **stats}
                for date_key, stats in sorted(daily_buckets.items(), reverse=True)
            ],
            "logs": [
                {
                    "id": item.id,
                    "action": item.action,
                    "book_id": item.book_id,
                    "book_title": book_title,
                    "prompt_tokens": item.prompt_tokens,
                    "completion_tokens": item.completion_tokens,
                    "total_tokens": item.total_tokens,
                    "cost_toman": item.cost_toman,
                    "created_at": utc_iso(item.created_at),
                }
                for item, book_title in log_rows
            ],
            "transactions": [
                {
                    "id": tx.id,
                    "plan_code": tx.plan_code,
                    "plan_name": tx.plan_name,
                    "amount_toman": tx.amount_toman,
                    "tokens_granted": tx.tokens_granted,
                    "duration_days": tx.duration_days,
                    "provider": tx.provider,
                    "status": tx.status,
                    "ref_id": tx.ref_id,
                    "created_at": utc_iso(tx.created_at),
                    "paid_at": utc_iso(tx.paid_at),
                }
                for tx in payments
            ],
        }


class AdminPreferencesPatchBody(BaseModel):
    general: dict[str, Any] | None = None
    appearance: dict[str, Any] | None = None
    notifications: dict[str, Any] | None = None
    privacy: dict[str, Any] | None = None


class AdminPreferencesResetBody(BaseModel):
    section: Literal["all", "general", "appearance", "notifications", "privacy"] = "appearance"


@protected_router.get("/preferences")
async def get_admin_preferences(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    async with async_session_factory() as session:
        billing = await get_or_init_billing_settings(session)
        await session.commit()
        return {"preferences": normalize_preferences(billing.admin_preferences, strict=False)}


@protected_router.put("/preferences")
async def update_admin_preferences(
    body: AdminPreferencesPatchBody,
    response: Response,
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    patch: dict[str, Any] = {}
    for section in ("general", "appearance", "notifications", "privacy"):
        val = getattr(body, section)
        if val is not None:
            patch[section] = val

    async with async_session_factory() as session:
        billing = await get_or_init_billing_settings(session)
        try:
            updated = merge_preferences(billing.admin_preferences, patch)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        billing.admin_preferences = updated
        await session.commit()
        return {"preferences": updated}


@protected_router.post("/preferences/reset")
async def reset_admin_preferences(
    body: AdminPreferencesResetBody,
    response: Response,
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    defaults = default_preferences()
    async with async_session_factory() as session:
        billing = await get_or_init_billing_settings(session)
        if body.section == "all":
            billing.admin_preferences = defaults
        else:
            current = normalize_preferences(billing.admin_preferences, strict=False)
            current[body.section] = defaults[body.section]
            billing.admin_preferences = current
        await session.commit()
        return {"preferences": normalize_preferences(billing.admin_preferences, strict=False)}


def _build_snippet(text: str | None, term: str, max_len: int = 120) -> str:
    clean = " ".join((text or "").split())
    if not clean:
        return ""
    idx = clean.lower().find(term.lower())
    if idx < 0:
        return clean[:max_len] + ("…" if len(clean) > max_len else "")
    start = max(0, idx - 32)
    end = min(len(clean), idx + len(term) + 64)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(clean) else ""
    return f"{prefix}{clean[start:end]}{suffix}"


@protected_router.get("/search")
async def search_admin(
    response: Response,
    q: str = Query(default="", max_length=120),
    category: Literal["all", "books", "pages", "users", "plans"] = Query("all"),
    limit: int = Query(default=12, ge=1, le=30),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    term = q.strip()
    pattern = f"%{term}%" if term else None
    numeric_term = int(term) if term and term.isdigit() else None

    books_out: list[dict[str, object]] = []
    pages_out: list[dict[str, object]] = []
    users_out: list[dict[str, object]] = []
    plans_out: list[dict[str, object]] = []

    async with async_session_factory() as session:
        if category in ("all", "books"):
            book_stmt = (
                select(Book, Grade.number, Grade.title, Major.title)
                .join(Grade, Book.grade_id == Grade.id)
                .outerjoin(Major, Book.major_id == Major.id)
            )
            if pattern is not None:
                book_filters = [Book.title.ilike(pattern), Grade.title.ilike(pattern)]
                if numeric_term is not None:
                    book_filters.append(Book.id == numeric_term)
                    book_filters.append(Grade.number == numeric_term)
                book_stmt = book_stmt.where(or_(*book_filters))
            book_rows = (await session.execute(book_stmt.order_by(Book.id.desc()).limit(limit))).all()
            books_out = [
                {
                    "id": book.id,
                    "title": book.title,
                    "grade_number": grade_num,
                    "grade_title": grade_title,
                    "major_title": major_title,
                    "total_pdf_pages": book.total_pdf_pages,
                    "status": book.status.value if hasattr(book.status, "value") else book.status,
                }
                for book, grade_num, grade_title, major_title in book_rows
            ]

        if category in ("all", "pages"):
            page_stmt = select(BookPage, Book.title).join(Book, BookPage.book_id == Book.id)
            if pattern is not None:
                page_filters = [
                    BookPage.chapter_title.ilike(pattern),
                    BookPage.markdown_content.ilike(pattern),
                ]
                if numeric_term is not None:
                    page_filters.append(BookPage.pdf_page_index == numeric_term)
                    page_filters.append(BookPage.printed_page_number == numeric_term)
                page_stmt = page_stmt.where(or_(*page_filters))
            page_rows = (
                await session.execute(
                    page_stmt.order_by(BookPage.book_id.desc(), BookPage.pdf_page_index.asc()).limit(limit)
                )
            ).all()
            pages_out = [
                {
                    "book_id": page.book_id,
                    "book_title": book_title,
                    "pdf_page_index": page.pdf_page_index,
                    "printed_page_number": page.printed_page_number,
                    "chapter_number": page.chapter_number,
                    "chapter_title": page.chapter_title,
                    "status": page.status.value if hasattr(page.status, "value") else page.status,
                    "edited_by_human": bool(page.edited_by_human),
                    "snippet": _build_snippet(page.markdown_content or page.chapter_title, term) if term else _build_snippet(page.markdown_content or page.chapter_title, ""),
                }
                for page, book_title in page_rows
            ]

        if category in ("all", "users"):
            user_stmt = select(User)
            if pattern is not None:
                user_stmt = user_stmt.where(
                    or_(
                        User.phone_number.ilike(pattern),
                        User.full_name.ilike(pattern),
                        User.email.ilike(pattern),
                        User.plan_code.ilike(pattern),
                        User.plan_title.ilike(pattern),
                    )
                )
            user_rows = (await session.scalars(user_stmt.order_by(User.created_at.desc()).limit(limit))).all()
            users_out = [
                {
                    "id": u.id,
                    "phone_number": u.phone_number,
                    "full_name": u.full_name,
                    "plan_code": u.plan_code,
                    "plan_title": u.plan_title,
                    "tokens_remaining": u.tokens_remaining,
                    "is_active": u.is_active,
                }
                for u in user_rows
            ]

        if category in ("all", "plans"):
            plan_stmt = select(Plan)
            if pattern is not None:
                plan_stmt = plan_stmt.where(
                    or_(
                        Plan.name.ilike(pattern),
                        Plan.code.ilike(pattern),
                        Plan.description.ilike(pattern),
                    )
                )
            plan_rows = (await session.scalars(plan_stmt.order_by(Plan.sort_order.asc()).limit(limit))).all()
            plans_out = [
                {
                    "code": p.code,
                    "name": p.name,
                    "price_toman": p.price_toman,
                    "token_quota": p.token_quota,
                    "duration_days": p.duration_days,
                    "is_active": p.is_active,
                }
                for p in plan_rows
            ]

    return {
        "query": term,
        "books": books_out,
        "pages": pages_out,
        "users": users_out,
        "plans": plans_out,
    }


# ---------------------------------------------------------------------------
# All-in-one Admin Control Center: Overview, Book Lifecycle, Sessions & AI/Gateways
# ---------------------------------------------------------------------------


@protected_router.get("/overview")
async def get_admin_overview(response: Response) -> dict[str, object]:
    """Return full live system health, operational counts, review queue & recent telemetry."""
    response.headers["Cache-Control"] = "no-store"
    settings = get_settings()
    overrides = get_runtime_overrides()
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session_factory() as session:
        await session.execute(sql_text("SELECT 1"))

        books_total = int(await session.scalar(select(func.count()).select_from(Book)) or 0)
        book_status_rows = (
            await session.execute(select(Book.status, func.count()).group_by(Book.status))
        ).all()
        book_by_status = {
            (st.value if hasattr(st, "value") else str(st)): int(cnt)
            for st, cnt in book_status_rows
        }

        page_status_rows = (
            await session.execute(select(BookPage.status, func.count()).group_by(BookPage.status))
        ).all()
        page_by_status = {
            (st.value if hasattr(st, "value") else str(st)): int(cnt)
            for st, cnt in page_status_rows
        }
        pages_total = sum(page_by_status.values())

        users_total = int(await session.scalar(select(func.count()).select_from(User)) or 0)
        users_active = int(
            await session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True)))
            or 0
        )
        users_paid = int(
            await session.scalar(
                select(func.count()).select_from(User).where(User.plan_code.in_(["normal", "pro", "vip"]))
            )
            or 0
        )
        active_sessions = int(
            await session.scalar(
                select(func.count())
                .select_from(UserSession)
                .where(UserSession.revoked_at.is_(None), UserSession.expires_at > now)
            )
            or 0
        )
        chats_total = int(await session.scalar(select(func.count()).select_from(ChatSession)) or 0)
        exams_total = int(await session.scalar(select(func.count()).select_from(ExamSession)) or 0)

        files_agg = (
            await session.execute(
                select(
                    func.count(UserFile.id),
                    func.coalesce(func.sum(UserFile.size_bytes), 0),
                ).where(UserFile.status == "active")
            )
        ).first()
        user_files_count = int((files_agg[0] if files_agg else 0) or 0)
        user_files_bytes = int((files_agg[1] if files_agg else 0) or 0)

        tokens_used_total = int(
            await session.scalar(select(func.coalesce(func.sum(User.tokens_used_total), 0))) or 0
        )
        tokens_used_today = int(
            await session.scalar(
                select(func.coalesce(func.sum(TokenUsageLog.total_tokens), 0)).where(
                    TokenUsageLog.created_at >= start_of_day
                )
            )
            or 0
        )
        revenue_toman = int(
            await session.scalar(
                select(func.coalesce(func.sum(PaymentTransaction.amount_toman), 0)).where(
                    PaymentTransaction.status == "paid",
                    PaymentTransaction.provider != "admin_grant",
                )
            )
            or 0
        )

        review_rows = (
            await session.execute(
                select(BookPage, Book.title)
                .join(Book, BookPage.book_id == Book.id)
                .where(BookPage.status.in_([PageStatus.needs_review, PageStatus.failed]))
                .order_by(BookPage.book_id.desc(), BookPage.pdf_page_index.asc())
                .limit(15)
            )
        ).all()
        needs_review_pages = [
            {
                "book_id": p.book_id,
                "book_title": b_title,
                "pdf_page_index": p.pdf_page_index,
                "printed_page_number": p.printed_page_number,
                "chapter_title": p.chapter_title,
                "status": p.status.value if hasattr(p.status, "value") else str(p.status),
                "warnings": p.warnings or [],
                "error_message": p.error_message,
            }
            for p, b_title in review_rows
        ]

        tx_rows = (
            await session.execute(
                select(PaymentTransaction, User.phone_number, User.full_name)
                .join(User, PaymentTransaction.user_id == User.id)
                .order_by(PaymentTransaction.created_at.desc())
                .limit(15)
            )
        ).all()
        recent_transactions = [
            {
                "id": tx.id,
                "user_id": tx.user_id,
                "phone_number": phone,
                "full_name": full_name,
                "plan_code": tx.plan_code,
                "plan_name": tx.plan_name,
                "amount_toman": tx.amount_toman,
                "tokens_granted": tx.tokens_granted,
                "duration_days": tx.duration_days,
                "provider": tx.provider,
                "status": tx.status,
                "ref_id": tx.ref_id,
                "created_at": utc_iso(tx.created_at),
                "paid_at": utc_iso(tx.paid_at),
            }
            for tx, phone, full_name in tx_rows
        ]

        usage_rows = (
            await session.execute(
                select(TokenUsageLog, User.phone_number, User.full_name, Book.title)
                .join(User, TokenUsageLog.user_id == User.id)
                .outerjoin(Book, TokenUsageLog.book_id == Book.id)
                .order_by(TokenUsageLog.created_at.desc())
                .limit(20)
            )
        ).all()
        recent_usage_logs = [
            {
                "id": log.id,
                "user_id": log.user_id,
                "phone_number": phone,
                "full_name": full_name,
                "action": log.action,
                "book_id": log.book_id,
                "book_title": b_title,
                "prompt_tokens": log.prompt_tokens,
                "completion_tokens": log.completion_tokens,
                "total_tokens": log.total_tokens,
                "cost_toman": log.cost_toman,
                "created_at": utc_iso(log.created_at),
            }
            for log, phone, full_name, b_title in usage_rows
        ]

    return {
        "system": {
            "status": "ok",
            "mode": "demo" if settings.demo_mode else "production",
            "database": "sqlite" if str(getattr(settings, "database_url", "")).startswith("sqlite") else "postgresql",
            "vector_backend": getattr(settings, "vector_backend", "qdrant"),
            "sms_provider": getattr(settings, "sms_provider", "demo"),
            "payment_provider": getattr(settings, "payment_provider", "demo"),
            "llm_base_url": getattr(settings, "llm_base_url", None),
            "tutor_model": getattr(settings, "tutor_model", None),
            "vision_model_primary": getattr(settings, "vision_model_primary", None),
            "vision_model_escalation": getattr(settings, "vision_model_escalation", None),
            "speech_to_text_model": getattr(settings, "speech_to_text_model", None),
            "embedding_model": getattr(settings, "embedding_model", None),
            "has_llm_api_key": bool(getattr(settings, "llm_api_key", "")),
            "override_count": len(overrides),
        },
        "counts": {
            "books_total": books_total,
            "books_ready": book_by_status.get("ready", 0),
            "books_ingesting": book_by_status.get("ingesting", 0),
            "books_failed": book_by_status.get("failed", 0),
            "pages_total": pages_total,
            "pages_done": page_by_status.get("done", 0),
            "pages_needs_review": page_by_status.get("needs_review", 0),
            "pages_failed": page_by_status.get("failed", 0),
            "pages_pending": page_by_status.get("pending", 0),
            "users_total": users_total,
            "users_active": users_active,
            "users_paid": users_paid,
            "active_sessions": active_sessions,
            "chats_total": chats_total,
            "exams_total": exams_total,
            "user_files_count": user_files_count,
            "user_files_bytes": user_files_bytes,
            "tokens_used_total": tokens_used_total,
            "tokens_used_today": tokens_used_today,
            "revenue_toman": revenue_toman,
        },
        "needs_review_pages": needs_review_pages,
        "recent_transactions": recent_transactions,
        "recent_usage_logs": recent_usage_logs,
    }


class AdminBookPatchBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    grade_number: int | None = Field(default=None, ge=1, le=12)
    major_code: str | None = Field(default=None, max_length=64)
    status: Literal["created", "ingesting", "ready", "failed"] | None = None


@protected_router.patch("/books/{book_id}")
async def update_admin_book(book_id: int, body: AdminBookPatchBody) -> dict[str, object]:
    async with async_session_factory() as session:
        book = await session.get(Book, book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="کتاب مورد نظر یافت نشد.")

        fields = body.model_fields_set
        if "title" in fields and body.title is not None:
            cleaned_title = body.title.strip()
            if not cleaned_title:
                raise HTTPException(status_code=422, detail="عنوان کتاب نمی‌تواند خالی باشد.")
            book.title = cleaned_title

        current_grade = await session.get(Grade, book.grade_id)
        if current_grade is None:
            raise HTTPException(status_code=404, detail="پایهٔ کتاب یافت نشد.")

        target_grade = current_grade
        if "grade_number" in fields and body.grade_number is not None:
            found_grade = await session.scalar(select(Grade).where(Grade.number == body.grade_number))
            if found_grade is None:
                raise HTTPException(status_code=404, detail=f"پایهٔ {body.grade_number} یافت نشد.")
            target_grade = found_grade
            book.grade_id = target_grade.id

        if "major_code" in fields or target_grade.id != current_grade.id:
            if "major_code" in fields:
                candidate_major = body.major_code.strip() if body.major_code and body.major_code.strip() else None
            else:
                existing_major = await session.get(Major, book.major_id) if book.major_id else None
                candidate_major = existing_major.code if existing_major else None

            if not target_grade.has_major:
                candidate_major = None
            major_err = validate_major_code(target_grade.has_major, candidate_major)
            if major_err:
                raise HTTPException(status_code=422, detail=major_err)
            if target_grade.has_major and candidate_major:
                major_obj = await session.scalar(select(Major).where(Major.code == candidate_major))
                if major_obj is None:
                    raise HTTPException(status_code=404, detail=f"رشتهٔ «{candidate_major}» یافت نشد.")
                book.major_id = major_obj.id
            else:
                book.major_id = None

        if "status" in fields and body.status is not None:
            book.status = BookStatus(body.status)

        await session.commit()
        await session.refresh(book)

        grade_obj = await session.get(Grade, book.grade_id)
        major_obj = await session.get(Major, book.major_id) if book.major_id else None
        page_rows = (
            await session.execute(
                select(BookPage.status, func.count())
                .where(BookPage.book_id == book.id)
                .group_by(BookPage.status)
            )
        ).all()
        counts = {
            (st.value if hasattr(st, "value") else str(st)): int(cnt) for st, cnt in page_rows
        }
        return {
            "book": {
                "id": book.id,
                "title": book.title,
                "grade_id": book.grade_id,
                "grade_number": grade_obj.number if grade_obj else None,
                "major_id": book.major_id,
                "major_code": major_obj.code if major_obj else None,
                "total_pdf_pages": book.total_pdf_pages,
                "status": book.status.value if hasattr(book.status, "value") else str(book.status),
                "pages": counts,
            }
        }


@protected_router.post("/books/{book_id}/reindex")
async def reindex_admin_book(book_id: int) -> dict[str, object]:
    settings = get_settings()
    if settings.demo_mode:
        raise HTTPException(
            status_code=400,
            detail="در حالت نمایشی (Demo Mode) ایندکس برداری غیرفعال است. برای ایندکس‌سازی برداری، در بخش تنظیمات API حالت اجرا را به تولید واقعی تغییر دهید.",
        )
    try:
        result = await index_book(book_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Vector reindex failed for book %s", book_id)
        raise HTTPException(
            status_code=503,
            detail=f"ایندکس برداری کتاب با خطا مواجه شد: {str(exc)[:220]}",
        ) from exc
    return {
        "ok": True,
        "vector_backend": settings.vector_backend,
        "embedding_model": settings.embedding_model,
        **result,
    }


@protected_router.post("/books/{book_id}/reprocess")
async def reprocess_admin_book(
    book_id: int,
    background_tasks: BackgroundTasks,
) -> dict[str, object]:
    settings = get_settings()
    async with async_session_factory() as session:
        book = await session.get(Book, book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="کتاب مورد نظر یافت نشد.")
        pdf_path = Path(book.pdf_file_path)
        if pdf_path.suffix.lower() != ".pdf" or not pdf_path.is_file():
            raise HTTPException(
                status_code=422,
                detail="فایل PDF اصلی این کتاب برای پردازش مجدد در دسترس نیست (یا کتاب از نوع متنی ساختاریافته است).",
            )
        grade = await session.get(Grade, book.grade_id)
        if grade is None:
            raise HTTPException(status_code=404, detail="پایهٔ کتاب یافت نشد.")
        major = await session.get(Major, book.major_id) if book.major_id else None
        existing_indices = list(
            (
                await session.scalars(
                    select(BookPage.pdf_page_index)
                    .where(BookPage.book_id == book_id)
                    .order_by(BookPage.pdf_page_index.asc())
                )
            ).all()
        )
        try:
            page_count = pdf_page_count(pdf_path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="فایل PDF کتاب معتبر نیست.") from exc

        start_page = min(existing_indices) if existing_indices else 1
        end_page = max(existing_indices) if existing_indices else min(page_count, max(1, book.total_pdf_pages))
        end_page = min(end_page, page_count)
        start_page = min(start_page, end_page)

        book.status = BookStatus.ingesting
        await session.commit()

        from app.services import kb_ingestion_service

        job = await kb_ingestion_service.create_ingestion_job(
            session, book_id=book.id, start_page=start_page, end_page=end_page
        )
        background_tasks.add_task(
            _run_ingest_background,
            book_id=book.id,
            pdf_path=pdf_path,
            grade_number=grade.number,
            major_code=major.code if major else None,
            book_title=book.title,
            start_page=start_page,
            end_page=end_page,
            model_primary=settings.vision_model_primary,
            model_escalation=settings.vision_model_escalation,
            escalate_figures=settings.escalate_figures,
            job_id=job.id,
        )
        return {
            "book_id": book.id,
            "status": "ingesting",
            "start_page": start_page,
            "end_page": end_page,
            "job_id": job.id,
            "total_pages": end_page - start_page + 1,
        }


@protected_router.delete("/books/{book_id}")
async def delete_admin_book(
    book_id: int,
    force: bool = Query(default=False),
) -> dict[str, object]:
    async with async_session_factory() as session:
        book = await session.get(Book, book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="کتاب مورد نظر یافت نشد.")

        chat_count = int(
            await session.scalar(
                select(func.count()).select_from(ChatSession).where(ChatSession.book_id == book_id)
            )
            or 0
        )
        exam_count = int(
            await session.scalar(
                select(func.count()).select_from(ExamSession).where(ExamSession.book_id == book_id)
            )
            or 0
        )
        if (chat_count > 0 or exam_count > 0) and not force:
            raise HTTPException(
                status_code=409,
                detail=f"این کتاب دارای {chat_count} گفت‌وگو و {exam_count} آزمون ثبت‌شده است. برای حذف کامل همراه با سوابق وابسته، تأیید حذف اجباری را بزنید.",
            )

        pdf_file_path = book.pdf_file_path
        if chat_count > 0:
            await session.execute(delete(ChatSession).where(ChatSession.book_id == book_id))
        if exam_count > 0:
            await session.execute(delete(ExamSession).where(ExamSession.book_id == book_id))
        await session.execute(delete(BookPage).where(BookPage.book_id == book_id))
        await session.delete(book)
        await session.commit()

    # Clean up storage & vector records best-effort
    try:
        storage_book_dir = STORAGE_DIR / "books" / str(book_id)
        if storage_book_dir.exists():
            shutil.rmtree(storage_book_dir, ignore_errors=True)
        if pdf_file_path:
            pdf_candidate = Path(pdf_file_path)
            if pdf_candidate.is_file() and pdf_candidate.parent != STORAGE_DIR / "demo":
                pdf_candidate.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        logger.warning("Cleanup of deleted book %s files partially failed", book_id)

    return {
        "deleted": True,
        "book_id": book_id,
        "deleted_chats": chat_count,
        "deleted_exams": exam_count,
    }


@protected_router.get("/users/{user_id}/sessions")
async def get_admin_user_sessions(user_id: str) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
        rows = (
            await session.scalars(
                select(UserSession)
                .where(UserSession.user_id == user_id)
                .order_by(UserSession.created_at.desc())
                .limit(30)
            )
        ).all()
        items = []
        for s in rows:
            exp = s.expires_at if s.expires_at.tzinfo is not None else s.expires_at.replace(tzinfo=timezone.utc)
            items.append(
                {
                    "id": s.id,
                    "user_agent": s.user_agent,
                    "ip_address": s.ip_address,
                    "is_active": s.revoked_at is None and exp > now,
                    "last_seen_at": utc_iso(s.last_seen_at),
                    "expires_at": utc_iso(s.expires_at),
                    "revoked_at": utc_iso(s.revoked_at),
                    "created_at": utc_iso(s.created_at),
                }
            )
        return {"user_id": user_id, "sessions": items}


@protected_router.post("/users/{user_id}/revoke-sessions")
async def revoke_admin_user_sessions(user_id: str) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
        result = await session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.commit()
        return {"user_id": user_id, "revoked_count": int(result.rowcount or 0)}


class AdminSettingsUpdateBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    config: dict[str, Any] | None = None
    clear_secrets: list[str] = Field(default_factory=list)
    clear_overrides: list[str] = Field(default_factory=list)


class AdminSettingsResetBody(BaseModel):
    section: Literal["all", "ai", "vector", "sms", "payment"] = "all"


class TestAiConnectionBody(BaseModel):
    llm_base_url: str | None = Field(default=None, max_length=512)
    llm_api_key: str | None = Field(default=None, max_length=512)
    test_model: str | None = Field(default=None, max_length=255)
    run_prompt: bool = False


class TestVectorBody(BaseModel):
    vector_backend: Literal["qdrant", "pgvector"] | None = None
    qdrant_url: str | None = Field(default=None, max_length=512)
    qdrant_collection: str | None = Field(default=None, max_length=128)


class TestSmsBody(BaseModel):
    sms_provider: Literal["demo", "kavenegar", "sms_ir", "webhook"] | None = None
    sms_api_key: str | None = Field(default=None, max_length=512)
    sms_sender: str | None = Field(default=None, max_length=128)
    sms_template: str | None = Field(default=None, max_length=128)
    sms_webhook_url: str | None = Field(default=None, max_length=512)
    test_phone: str | None = Field(default=None, max_length=24)


def _redact_secret(text: str, *secrets_to_hide: str | None) -> str:
    cleaned = text
    for sec in secrets_to_hide:
        if sec and len(sec) >= 4:
            cleaned = cleaned.replace(sec, "***")
    return cleaned[:280]


@protected_router.get("/settings")
async def get_admin_system_settings(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    async with async_session_factory() as session:
        billing = await get_or_init_billing_settings(session)
        persisted = normalize_persisted_overrides(getattr(billing, "system_config", {}))
        await session.commit()
    return serialize_admin_settings(get_base_settings(), get_settings(), persisted)


@protected_router.put("/settings")
async def update_admin_system_settings(
    body: AdminSettingsUpdateBody,
    response: Response,
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    raw_patch: dict[str, Any] = {}
    if body.config is not None:
        raw_patch.update(body.config)
    if body.model_extra:
        for k, v in body.model_extra.items():
            if k in ALL_RUNTIME_FIELDS:
                raw_patch[k] = v
            else:
                raise HTTPException(status_code=422, detail=f"تنظیم ناشناخته: {k}")

    async with async_session_factory() as session:
        billing = await get_or_init_billing_settings(session)
        try:
            updated = apply_runtime_patch(
                getattr(billing, "system_config", {}),
                raw_patch,
                clear_secrets=body.clear_secrets,
                clear_overrides=body.clear_overrides,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        billing.system_config = updated
        await session.commit()

    set_runtime_overrides(updated)
    await refresh_runtime_clients()
    return serialize_admin_settings(get_base_settings(), get_settings(), updated)


@protected_router.post("/settings/reset")
async def reset_admin_system_settings(
    body: AdminSettingsResetBody,
    response: Response,
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    keys_to_remove = RESET_SECTION_FIELDS[body.section]
    async with async_session_factory() as session:
        billing = await get_or_init_billing_settings(session)
        current = normalize_persisted_overrides(getattr(billing, "system_config", {}))
        if body.section == "all":
            next_config: dict[str, Any] = {}
        else:
            next_config = {k: v for k, v in current.items() if k not in keys_to_remove}
        billing.system_config = next_config
        await session.commit()

    set_runtime_overrides(next_config)
    await refresh_runtime_clients()
    return serialize_admin_settings(get_base_settings(), get_settings(), next_config)


@protected_router.post("/settings/test-ai")
async def test_ai_connection(body: TestAiConnectionBody) -> dict[str, object]:
    """Probe an OpenAI-compatible AI API (`/models` + optional tiny completion) safely.

    All outbound provider traffic lives in :mod:`app.services.ai_gateway`; this route
    only validates input and forwards to :func:`ai_gateway.probe_endpoint`, which also
    scrubs the API key from any upstream error text before it reaches the client.
    """
    from app.services.ai_gateway import probe_endpoint

    settings = get_settings()
    base_url = (body.llm_base_url or settings.llm_base_url or "").strip().rstrip("/")
    api_key = (body.llm_api_key or settings.llm_api_key or "").strip()
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="آدرس پایه API هوش مصنوعی باید با http:// یا https:// شروع شود.")
    if not api_key:
        raise HTTPException(status_code=422, detail="کلید API برای تست اتصال وارد نشده است.")

    probe_model = (
        body.test_model or settings.tutor_model or settings.vision_model_primary or ""
    ).strip()

    probe = await probe_endpoint(
        base_url=base_url,
        api_key=api_key,
        model=probe_model if body.run_prompt else None,
        run_prompt=body.run_prompt,
    )

    prompt_test = probe.get("prompt_test")
    return {
        "ok": bool(probe.get("ok")) or bool(isinstance(prompt_test, dict) and prompt_test.get("ok")),
        "base_url": probe.get("base_url"),
        "status_code": probe.get("status_code"),
        "latency_ms": probe.get("latency_ms"),
        "models": list(probe.get("models") or []),
        "models_count": int(probe.get("models_count") or 0),
        "error": probe.get("error"),
        "prompt_test": prompt_test,
    }


@protected_router.post("/settings/test-vector")
async def test_vector_connection(body: TestVectorBody) -> dict[str, object]:
    """Check the configured vector backend (pgvector extension or Qdrant collections).

    Qdrant transport lives in :func:`app.services.retrieval_service.probe_qdrant`.
    """
    from app.services.retrieval_service import probe_qdrant

    settings = get_settings()
    backend = body.vector_backend or settings.vector_backend
    started = time.perf_counter()

    if backend == "pgvector":
        is_sqlite = str(getattr(settings, "database_url", "")).startswith("sqlite")
        if is_sqlite:
            return {
                "ok": False,
                "backend": "pgvector",
                "latency_ms": max(1, int(round((time.perf_counter() - started) * 1000))),
                "detail": "پایگاه‌داده فعلی SQLite است؛ افزونه pgvector نیازمند PostgreSQL/Supabase است (در حالت Demo از جستجوی واژگانی استفاده می‌شود).",
            }
        try:
            async with async_session_factory() as session:
                ext_present = bool(
                    await session.scalar(
                        sql_text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                    )
                )
                table_exists = bool(
                    await session.scalar(
                        sql_text(
                            "SELECT 1 FROM information_schema.tables "
                            "WHERE table_schema = 'public' AND table_name = 'book_page_embeddings'"
                        )
                    )
                )
                vectors_count = 0
                if table_exists:
                    vectors_count = int(
                        await session.scalar(sql_text("SELECT COUNT(*) FROM public.book_page_embeddings"))
                        or 0
                    )
            return {
                "ok": ext_present,
                "backend": "pgvector",
                "latency_ms": max(1, int(round((time.perf_counter() - started) * 1000))),
                "detail": (
                    f"افزونه pgvector فعال است؛ تعداد {vectors_count} بردار صفحه ذخیره شده."
                    if ext_present
                    else "افزونه vector در PostgreSQL نصب یا فعال نشده است (CREATE EXTENSION vector)."
                ),
                "collection_info": {
                    "extension_enabled": ext_present,
                    "table_exists": table_exists,
                    "vectors_count": vectors_count,
                },
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "backend": "pgvector",
                "latency_ms": max(1, int(round((time.perf_counter() - started) * 1000))),
                "detail": f"خطا در بررسی pgvector: {str(exc)[:220]}",
            }

    result = await probe_qdrant(body.qdrant_url, body.qdrant_collection)
    if result.pop("invalid_url", False):
        raise HTTPException(status_code=422, detail="آدرس Qdrant معتبر نیست.")
    return result


@protected_router.post("/settings/test-sms")
async def test_sms_gateway(body: TestSmsBody) -> dict[str, object]:
    settings = get_settings()
    provider_name = body.sms_provider or settings.sms_provider
    api_key = body.sms_api_key if body.sms_api_key else settings.sms_api_key
    sender = body.sms_sender if body.sms_sender is not None else settings.sms_sender
    template = body.sms_template if body.sms_template is not None else settings.sms_template
    webhook_url = body.sms_webhook_url if body.sms_webhook_url is not None else settings.sms_webhook_url

    if provider_name in ("kavenegar", "sms_ir") and not api_key:
        return {
            "ok": False,
            "provider": provider_name,
            "detail": f"برای درگاه {provider_name} وارد کردن کلید API الزامی است.",
        }
    if provider_name == "sms_ir" and not template:
        return {
            "ok": False,
            "provider": provider_name,
            "detail": "برای درگاه sms.ir وارد کردن شناسه قالب (Template ID) الزامی است.",
        }
    if provider_name == "webhook" and not webhook_url:
        return {
            "ok": False,
            "provider": provider_name,
            "detail": "برای حالت Webhook وارد کردن آدرس Webhook URL الزامی است.",
        }

    if body.test_phone and body.test_phone.strip():
        try:
            phone = normalize_iranian_phone(body.test_phone)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        probe_settings = settings.model_copy(
            update={
                "sms_provider": provider_name,
                "sms_api_key": api_key,
                "sms_sender": sender,
                "sms_template": template,
                "sms_webhook_url": webhook_url,
            }
        )
        try:
            delivery = await get_sms_provider(probe_settings).send_otp(phone_number=phone, code="123456")
            return {
                "ok": True,
                "provider": delivery.provider,
                "detail": f"ارسال آزمایشی کد به {phone} از طریق {delivery.provider} با موفقیت انجام شد.",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "provider": provider_name,
                "detail": f"خطا در ارسال آزمایشی پیامک: {_redact_secret(str(exc), api_key)}",
            }

    return {
        "ok": True,
        "provider": provider_name,
        "detail": (
            "حالت آزمایشی (Demo) فعال است؛ کد ورود مستقیماً در پاسخ نمایش داده می‌شود."
            if provider_name == "demo"
            else f"پیکربندی درگاه {provider_name} کامل است و آماده ارسال پیامک است."
        ),
    }



# ---------------------------------------------------------------------------
# PHASE 1 — AI Provider Vault, Model Routing, Quotas, Observability & RBAC
# ---------------------------------------------------------------------------

FEATURE_ROUTE_LABELS: dict[str, str] = {
    "chat": "گفت‌وگوی معلم",
    "solve": "حل تمرین",
    "quiz": "طراحی آزمون",
    "vision_ocr": "خواندن تصویر دانش‌آموز",
    "stt": "تبدیل گفتار به متن",
    "embedding": "بردارسازی (RAG)",
    "flashcards": "فلش‌کارت",
    "ingest_ocr": "پردازش کتاب (OCR)",
    "memory": "حافظهٔ یادگیرنده (L2/L3)",
    "intent_router": "مسیریاب هوشمند حالت‌ها",
}


class AiProviderCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    provider_type: Literal["openai", "anthropic", "gemini", "openai_compatible", "local"]
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=512)
    capabilities: list[str] = Field(default_factory=list)
    is_active: bool = True


class AiProviderUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    provider_type: Literal["openai", "anthropic", "gemini", "openai_compatible", "local"] | None = None
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=512)
    clear_api_key: bool = False
    capabilities: list[str] | None = None
    is_active: bool | None = None


class FeatureRouteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_key: str = Field(min_length=1, max_length=64)
    provider_id: int = Field(gt=0)
    model_name: str = Field(min_length=1, max_length=255)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    fallback_provider_id: int | None = Field(default=None, gt=0)
    fallback_model_name: str | None = Field(default=None, max_length=255)
    is_active: bool = True


class QuotaPolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_tokens: int | None = Field(default=None, ge=0)
    monthly_tokens: int | None = Field(default=None, ge=0)
    daily_requests: int | None = Field(default=None, ge=0)
    requests_per_minute: int | None = Field(default=None, ge=0)


class AdminUserRoleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["admin", "teacher", "student", "guardian"] | None = None
    grade_level: int | None = Field(default=None, ge=1, le=12)
    major: str | None = Field(default=None, max_length=64)
    plan_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None


class AuditFlagBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=255)


@protected_router.get("/providers")
async def list_ai_providers(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    """List configured providers. API keys are never returned in plaintext."""
    from app.services.ai_provider_service import serialize_provider

    rows = (
        await session.scalars(select(AiProvider).order_by(AiProvider.id.asc()))
    ).all()
    return {
        "providers": [serialize_provider(provider) for provider in rows],
        "provider_types": list(PROVIDER_TYPES),
        "capabilities": list(PROVIDER_CAPABILITIES),
    }


@protected_router.post("/providers")
async def create_ai_provider(
    body: AiProviderCreateBody, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    from app.services.ai_provider_service import (
        normalize_capabilities,
        serialize_provider,
        set_provider_api_key,
        validate_provider_type,
    )

    try:
        provider_type = validate_provider_type(body.provider_type)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if await session.scalar(select(AiProvider).where(AiProvider.name == body.name.strip())):
        raise HTTPException(status_code=409, detail="ارائه‌دهنده‌ای با این نام از قبل وجود دارد.")

    provider = AiProvider(
        name=body.name.strip(),
        provider_type=provider_type,
        base_url=(body.base_url or "").strip().rstrip("/") or None,
        capabilities=normalize_capabilities(body.capabilities),
        is_active=body.is_active,
    )
    set_provider_api_key(provider, body.api_key)
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return {"provider": serialize_provider(provider)}


@protected_router.put("/providers/{provider_id}")
async def update_ai_provider(
    provider_id: int,
    body: AiProviderUpdateBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    from app.services.ai_provider_service import (
        normalize_capabilities,
        serialize_provider,
        set_provider_api_key,
    )

    provider = await session.get(AiProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="ارائه‌دهنده پیدا نشد.")

    if body.name is not None and body.name.strip() != provider.name:
        clash = await session.scalar(select(AiProvider).where(AiProvider.name == body.name.strip()))
        if clash is not None:
            raise HTTPException(status_code=409, detail="ارائه‌دهنده‌ای با این نام از قبل وجود دارد.")
        provider.name = body.name.strip()
    if body.provider_type is not None:
        provider.provider_type = body.provider_type
    if body.base_url is not None:
        provider.base_url = body.base_url.strip().rstrip("/") or None
    if body.capabilities is not None:
        provider.capabilities = normalize_capabilities(body.capabilities)
    if body.is_active is not None:
        provider.is_active = body.is_active
    if body.clear_api_key:
        provider.encrypted_api_key = None
    elif body.api_key is not None and body.api_key.strip():
        set_provider_api_key(provider, body.api_key)

    await session.commit()
    await session.refresh(provider)
    return {"provider": serialize_provider(provider)}


@protected_router.delete("/providers/{provider_id}")
async def delete_ai_provider(
    provider_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    provider = await session.get(AiProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="ارائه‌دهنده پیدا نشد.")
    in_use = await session.scalar(
        select(func.count())
        .select_from(FeatureModelRoute)
        .where(
            or_(
                FeatureModelRoute.provider_id == provider_id,
                FeatureModelRoute.fallback_provider_id == provider_id,
            )
        )
    )
    if in_use:
        raise HTTPException(
            status_code=409,
            detail="این ارائه‌دهنده در مسیر مدل‌ها استفاده می‌شود؛ ابتدا مسیرها را تغییر دهید.",
        )
    await session.delete(provider)
    await session.commit()
    return {"deleted": True, "id": provider_id}


@protected_router.post("/providers/{provider_id}/test")
async def test_ai_provider(
    provider_id: int,
    session: AsyncSession = Depends(get_session),
    run_prompt: bool = Query(default=True),
) -> dict[str, object]:
    """Live connectivity test for one stored provider (key decrypted server-side only)."""
    from datetime import datetime, timezone

    from app.services.ai_gateway import probe_provider

    provider = await session.get(AiProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="ارائه‌دهنده پیدا نشد.")

    route = await session.scalar(
        select(FeatureModelRoute)
        .where(FeatureModelRoute.provider_id == provider_id, FeatureModelRoute.is_active.is_(True))
        .order_by(FeatureModelRoute.id.asc())
    )
    result = await probe_provider(
        provider, provider_model=route.model_name if route else None, run_prompt=run_prompt
    )
    provider.last_test_status = "ok" if result.get("ok") else "failed"
    provider.last_test_latency_ms = int(result.get("latency_ms") or 0)
    provider.last_test_at = datetime.now(timezone.utc)
    await session.commit()
    return result


@protected_router.get("/routes")
async def list_feature_routes(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    from app.services.ai_provider_service import serialize_route

    rows = (
        await session.scalars(select(FeatureModelRoute).order_by(FeatureModelRoute.feature_key.asc()))
    ).all()
    providers = (await session.scalars(select(AiProvider).order_by(AiProvider.id.asc()))).all()
    return {
        "routes": [serialize_route(route) for route in rows],
        "providers": [
            {"id": p.id, "name": p.name, "is_active": p.is_active, "capabilities": list(p.capabilities or [])}
            for p in providers
        ],
        "feature_keys": [
            {"key": key, "label_fa": label} for key, label in FEATURE_ROUTE_LABELS.items()
        ],
    }


@protected_router.put("/routes")
async def upsert_feature_route(
    body: FeatureRouteBody, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    from app.services.ai_provider_service import ROUTABLE_FEATURE_KEYS, serialize_route

    if body.feature_key not in ROUTABLE_FEATURE_KEYS:
        raise HTTPException(status_code=422, detail="کلید قابلیت انتخاب‌شده معتبر نیست.")
    if await session.get(AiProvider, body.provider_id) is None:
        raise HTTPException(status_code=422, detail="ارائه‌دهندهٔ انتخاب‌شده پیدا نشد.")
    if body.fallback_provider_id is not None and await session.get(AiProvider, body.fallback_provider_id) is None:
        raise HTTPException(status_code=422, detail="ارائه‌دهندهٔ جایگزین پیدا نشد.")

    route = await session.scalar(
        select(FeatureModelRoute).where(FeatureModelRoute.feature_key == body.feature_key)
    )
    if route is None:
        route = FeatureModelRoute(feature_key=body.feature_key)
        session.add(route)
    route.provider_id = body.provider_id
    route.model_name = body.model_name.strip()
    route.temperature = body.temperature
    route.max_tokens = body.max_tokens
    route.fallback_provider_id = body.fallback_provider_id
    route.fallback_model_name = (body.fallback_model_name or "").strip() or None
    route.is_active = body.is_active
    await session.commit()
    await session.refresh(route)
    return {"route": serialize_route(route)}


@protected_router.delete("/routes/{feature_key}")
async def delete_feature_route(
    feature_key: str, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    route = await session.scalar(
        select(FeatureModelRoute).where(FeatureModelRoute.feature_key == feature_key)
    )
    if route is None:
        raise HTTPException(status_code=404, detail="مسیر مدل موردنظر پیدا نشد.")
    await session.delete(route)
    await session.commit()
    return {"deleted": True, "feature_key": feature_key}


@protected_router.get("/quotas")
async def get_quota_policy(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    from app.services.quota_service import DEFAULT_QUOTA_POLICY, get_quota_policy as read_policy

    policy = await read_policy(session)
    return {"policy": policy, "defaults": DEFAULT_QUOTA_POLICY}


@protected_router.put("/quotas")
async def update_quota_policy(
    body: QuotaPolicyBody, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    """Persist a quota policy override in `billing_settings.system_config["quotas"]`."""
    from app.services.quota_service import DEFAULT_QUOTA_POLICY, QUOTA_POLICY_KEY

    billing = await get_or_init_billing_settings(session)
    config = dict(billing.system_config or {})
    current = dict(DEFAULT_QUOTA_POLICY)
    stored = config.get(QUOTA_POLICY_KEY)
    if isinstance(stored, dict):
        current.update({k: v for k, v in stored.items() if k in current and isinstance(v, int)})
    for key, value in body.model_dump(exclude_none=True).items():
        if key in current:
            current[key] = int(value)
    config[QUOTA_POLICY_KEY] = current
    billing.system_config = config
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(billing, "system_config")
    await session.commit()
    return {"policy": current}


@protected_router.get("/users/{user_id}/quota")
async def get_user_quota(
    user_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    from app.services.quota_service import get_quota_snapshot

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد.")
    snapshot = await get_quota_snapshot(session, user_id=user_id)
    await session.commit()
    return {"user_id": user_id, "quota": snapshot}


@protected_router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str, body: AdminUserRoleBody, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    """Admin-only RBAC editing: role, grade level, major, plan, activation."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد.")
    if body.role is not None:
        user.role = body.role
    if body.grade_level is not None:
        user.grade_level = body.grade_level
    if body.major is not None:
        user.major = body.major.strip() or None
    if body.plan_id is not None:
        user.plan_id = body.plan_id
    if body.is_active is not None:
        user.is_active = body.is_active
    await session.commit()
    await session.refresh(user)
    return {
        "user": {
            "id": user.id,
            "role": user.role,
            "grade_level": user.grade_level,
            "major": user.major,
            "plan_id": user.plan_id,
            "is_active": user.is_active,
        }
    }


@protected_router.get("/audit-logs")
async def list_audit_logs(
    session: AsyncSession = Depends(get_session),
    feature_key: str | None = Query(default=None, max_length=64),
    status: Literal["success", "error", "blocked", "flagged"] | None = Query(default=None),
    user_id: str | None = Query(default=None, max_length=36),
    flagged_only: bool = Query(default=False),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    """Filterable glass-box audit trail (Rule 3)."""
    stmt = select(AiAuditLog)
    count_stmt = select(func.count()).select_from(AiAuditLog)
    conditions = []
    if feature_key:
        conditions.append(AiAuditLog.feature_key == feature_key)
    if status:
        conditions.append(AiAuditLog.status == status)
    if user_id:
        conditions.append(AiAuditLog.user_id == user_id)
    if flagged_only:
        conditions.append(AiAuditLog.status == "flagged")
    if date_from is not None:
        conditions.append(AiAuditLog.created_at >= date_from)
    if date_to is not None:
        conditions.append(AiAuditLog.created_at <= date_to)
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = int(await session.scalar(count_stmt) or 0)
    rows = (
        await session.scalars(
            stmt.order_by(AiAuditLog.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_serialize_audit_summary(row) for row in rows],
    }


@protected_router.get("/audit-logs/summary")
async def audit_summary(
    session: AsyncSession = Depends(get_session),
    days: int = Query(default=7, ge=1, le=90),
) -> dict[str, object]:
    """Token & cost summary cards: totals, by day, by feature, by user."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await session.execute(
            select(
                AiAuditLog.feature_key,
                AiAuditLog.user_id,
                AiAuditLog.tokens_in,
                AiAuditLog.tokens_out,
                AiAuditLog.estimated_cost_usd,
                AiAuditLog.status,
                AiAuditLog.created_at,
            ).where(AiAuditLog.created_at >= since)
        )
    ).all()

    totals = {
        "calls": len(rows),
        "tokens_in": 0,
        "tokens_out": 0,
        "estimated_cost_usd": 0.0,
        "errors": 0,
        "flagged": 0,
    }
    by_feature: dict[str, dict[str, float]] = {}
    by_day: dict[str, dict[str, float]] = {}
    by_user: dict[str, dict[str, float]] = {}
    for feature, user, tokens_in, tokens_out, cost, status, created in rows:
        totals["tokens_in"] += int(tokens_in or 0)
        totals["tokens_out"] += int(tokens_out or 0)
        totals["estimated_cost_usd"] = round(
            float(totals["estimated_cost_usd"]) + float(cost or 0), 6
        )
        if status == "error":
            totals["errors"] += 1
        if status == "flagged":
            totals["flagged"] += 1
        day = created.strftime("%Y-%m-%d") if created else "unknown"
        for bucket, key in ((by_feature, feature), (by_day, day), (by_user, user or "anonymous")):
            entry = bucket.setdefault(
                key, {"calls": 0, "tokens_in": 0, "tokens_out": 0, "estimated_cost_usd": 0.0}
            )
            entry["calls"] += 1
            entry["tokens_in"] += int(tokens_in or 0)
            entry["tokens_out"] += int(tokens_out or 0)
            entry["estimated_cost_usd"] = round(
                entry["estimated_cost_usd"] + float(cost or 0), 6
            )
    return {
        "days": days,
        "totals": totals,
        "by_feature": by_feature,
        "by_day": dict(sorted(by_day.items())),
        "by_user": by_user,
    }


@protected_router.get("/audit-logs/{audit_id}")
async def get_audit_log(
    audit_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    row = await session.get(AiAuditLog, audit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="رکورد موردنظر پیدا نشد.")
    return {"item": _serialize_audit_detail(row)}


@protected_router.post("/audit-logs/{audit_id}/flag")
async def flag_audit_log(
    audit_id: str,
    body: AuditFlagBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    row = await session.get(AiAuditLog, audit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="رکورد موردنظر پیدا نشد.")
    identity = getattr(request.state, "admin_identity", None) or {}
    row.status = "flagged"
    row.flag_reason = (body.reason or "admin_review").strip()[:255]
    row.flagged_by = identity.get("user_id")
    await session.commit()
    return {"item": _serialize_audit_summary(row)}


def _serialize_audit_summary(row: AiAuditLog) -> dict[str, object]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "session_id": row.session_id,
        "feature_key": row.feature_key,
        "provider_id": row.provider_id,
        "model_name": row.model_name,
        "tokens_in": row.tokens_in,
        "tokens_out": row.tokens_out,
        "estimated_cost_usd": row.estimated_cost_usd,
        "latency_ms": row.latency_ms,
        "status": row.status,
        "rag_hit_count": row.rag_hit_count,
        "flag_reason": row.flag_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "preview": (row.response_text or "")[:160],
    }


def _serialize_audit_detail(row: AiAuditLog) -> dict[str, object]:
    payload = _serialize_audit_summary(row)
    payload.update(
        {
            "request_messages_json": row.request_messages_json or [],
            "response_text": row.response_text,
            "rag_citations_json": row.rag_citations_json or [],
            "error_message": row.error_message,
            "skill_id": row.skill_id,
            "flagged_by": row.flagged_by,
        }
    )
    return payload


router.include_router(protected_router)
