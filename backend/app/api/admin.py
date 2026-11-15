"""Admin API: password-protected book upload + ingestion, status, preview, manual fix."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import logging
import secrets
import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.auth import PaymentTransaction, Plan, TokenUsageLog, User
from app.models.curriculum import Book, BookPage, Grade, Major
from app.services.auth_billing_service import (
    apply_plan_to_user,
    calculate_token_cost_toman,
    get_or_init_billing_settings,
    get_or_init_plans,
    get_user_today_tokens,
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
from app.services.validation import validate_major_code

ADMIN_COOKIE_NAME = "iran_tutor_admin"
MAX_PDF_BYTES = 100 * 1024 * 1024
logger = logging.getLogger(__name__)


def _admin_signing_key() -> bytes:
    settings = get_settings()
    material = (
        f"iran-tutor-admin-v2:{settings.admin_username}:{settings.admin_password}:{settings.llm_api_key}"
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


def require_admin(request: Request) -> None:
    if not _is_admin_authenticated(request):
        logger.warning(
            "Admin auth failed for %s; header_keys=%s has_cookie=%s",
            request.url.path,
            sorted(k for k in request.headers.keys() if k in {"authorization", "x-admin-token", "cookie"}),
            ADMIN_COOKIE_NAME in request.cookies,
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


@protected_router.post("/books/upload-and-ingest")
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
                "visual_elements": row.visual_elements or [],
                "extraction_model": row.extraction_model,
                "edited_by_human": bool(row.edited_by_human),
                "error_message": row.error_message,
                "image_url": f"/api/v1/admin/books/{book_id}/pages/{row.pdf_page_index}/image",
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
        return {"book_id": book_id, "pdf_page_index": idx, "status": "done", "edited_by_human": True}


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


class PlanUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    price_toman: int | None = Field(default=None, ge=0, le=1_000_000_000)
    token_quota: int | None = Field(default=None, ge=1, le=1_000_000_000)
    duration_days: int | None = Field(default=None, ge=1, le=3650)
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
        await session.commit()
        await session.refresh(billing)
        return {
            "settings": {
                "token_price_per_1k_toman": billing.token_price_per_1k_toman,
                "starter_tokens": billing.starter_tokens,
                "starter_duration_days": billing.starter_duration_days,
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
        return {
            "user": serialize_user(
                user,
                today_tokens=today_tokens,
                token_price_per_1k_toman=billing.token_price_per_1k_toman,
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

        return {
            "user": serialize_user(
                user,
                today_tokens=today_tokens,
                token_price_per_1k_toman=billing.token_price_per_1k_toman,
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


router.include_router(protected_router)
