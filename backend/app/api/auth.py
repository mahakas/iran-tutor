"""Student SMS OTP authentication and profile endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import extract_user_token, get_optional_student, require_student
from app.core.config import get_settings
from app.db.session import get_session
from app.models.auth import OtpCode, User, UserSession
from app.services.account_service import get_user_storage_quota_bytes
from app.services.auth_billing_service import (
    USER_COOKIE_NAME,
    apply_plan_to_user,
    create_user_session_token,
    get_or_init_billing_settings,
    get_user_today_tokens,
    hash_otp_code,
    normalize_iranian_phone,
    parse_user_session_token,
    serialize_user,
    verify_otp_hash,
)
from app.services.sms_provider import get_sms_provider

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RequestOtpBody(BaseModel):
    phone_number: str = Field(min_length=9, max_length=24)


class VerifyOtpBody(BaseModel):
    phone_number: str = Field(min_length=9, max_length=24)
    code: str = Field(min_length=4, max_length=10)
    full_name: str | None = Field(default=None, max_length=120)


class UpdateProfileBody(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)


def _is_https(request: Request) -> bool:
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
    )


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@router.post("/request-otp")
async def request_otp(
    body: RequestOtpBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    try:
        phone = normalize_iranian_phone(body.phone_number)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    settings = get_settings()
    now = datetime.now(timezone.utc)

    latest = await session.scalar(
        select(OtpCode)
        .where(OtpCode.phone_number == phone)
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    if latest is not None and settings.otp_resend_seconds > 0:
        elapsed = (now - _utc(latest.created_at)).total_seconds()
        if elapsed < settings.otp_resend_seconds and latest.consumed_at is None:
            wait_s = max(1, int(settings.otp_resend_seconds - elapsed))
            raise HTTPException(
                status_code=429,
                detail=f"لطفاً {wait_s} ثانیه دیگر برای ارسال مجدد کد صبر کنید.",
            )

    # Invalidate earlier unconsumed OTP codes for this number.
    await session.execute(
        update(OtpCode)
        .where(OtpCode.phone_number == phone, OtpCode.consumed_at.is_(None))
        .values(consumed_at=now)
    )

    code = f"{secrets.randbelow(900000) + 100000}"
    otp_id = str(uuid4())
    otp = OtpCode(
        id=otp_id,
        phone_number=phone,
        code_hash=hash_otp_code(otp_id, phone, code),
        attempts=0,
        max_attempts=settings.otp_max_attempts,
        expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
        created_at=now,
    )
    session.add(otp)
    await session.commit()

    provider = get_sms_provider(settings)
    try:
        delivery = await provider.send_otp(phone_number=phone, code=code)
    except Exception as error:  # noqa: BLE001
        logger.exception("SMS OTP delivery failed via %s", provider.provider_name)
        raise HTTPException(
            status_code=503,
            detail="ارسال پیامک در حال حاضر با خطا مواجه شد. لطفاً لحظاتی دیگر تلاش کنید.",
        ) from error

    payload: dict[str, object] = {
        "sent": True,
        "phone_number": phone,
        "provider": delivery.provider,
        "expires_in_seconds": settings.otp_ttl_seconds,
        "resend_after_seconds": settings.otp_resend_seconds,
    }
    if settings.demo_mode:
        payload["demo_code"] = code
    return payload


@router.post("/verify-otp")
async def verify_otp(
    body: VerifyOtpBody,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    try:
        phone = normalize_iranian_phone(body.phone_number)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    code_clean = body.code.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    if not code_clean.isdigit() or len(code_clean) != 6:
        raise HTTPException(status_code=422, detail="کد تأیید باید ۶ رقم باشد.")

    now = datetime.now(timezone.utc)
    otp = await session.scalar(
        select(OtpCode)
        .where(OtpCode.phone_number == phone, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    if otp is None:
        raise HTTPException(status_code=401, detail="کد فعالی برای این شماره یافت نشد. ابتدا درخواست کد بدهید.")

    if _utc(otp.expires_at) <= now:
        otp.consumed_at = now
        await session.commit()
        raise HTTPException(status_code=401, detail="کد تأیید منقضی شده است. لطفاً کد جدید دریافت کنید.")

    if otp.attempts >= otp.max_attempts:
        otp.consumed_at = now
        await session.commit()
        raise HTTPException(status_code=429, detail="تعداد تلاش‌های اشتباه بیش از حد مجاز است. کد جدید بگیرید.")

    if not verify_otp_hash(otp.id, phone, code_clean, otp.code_hash):
        otp.attempts += 1
        if otp.attempts >= otp.max_attempts:
            otp.consumed_at = now
        await session.commit()
        remaining = max(0, otp.max_attempts - otp.attempts)
        raise HTTPException(
            status_code=401,
            detail=f"کد واردشده نادرست است. ({remaining} تلاش باقی‌مانده)" if remaining else "کد باطل شد. کد جدید دریافت کنید.",
        )

    otp.consumed_at = now

    billing = await get_or_init_billing_settings(session)
    user = await session.scalar(select(User).where(User.phone_number == phone))
    is_new_user = user is None
    if user is None:
        user = User(
            phone_number=phone,
            full_name=body.full_name.strip() if body.full_name and body.full_name.strip() else None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        apply_plan_to_user(
            user,
            plan_code="trial",
            plan_name="هدیه ثبت‌نام",
            tokens_granted=billing.starter_tokens,
            duration_days=billing.starter_duration_days,
            carry_over_valid=False,
            now=now,
        )
        session.add(user)
    else:
        if not user.is_active:
            await session.commit()
            raise HTTPException(status_code=403, detail="حساب کاربری شما غیرفعال شده است.")
        if body.full_name and body.full_name.strip() and not user.full_name:
            user.full_name = body.full_name.strip()

    user.last_login_at = now
    await session.flush()

    settings = get_settings()
    token_nonce = secrets.token_hex(12)
    token = create_user_session_token(user.id, nonce=token_nonce)
    user_agent = (request.headers.get("user-agent") or "")[:512] or None
    forwarded_for = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    client_ip = (forwarded_for or (request.client.host if request.client else ""))[:64] or None
    session.add(
        UserSession(
            user_id=user.id,
            token_nonce=token_nonce,
            user_agent=user_agent,
            ip_address=client_ip,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=settings.user_session_ttl_seconds),
            created_at=now,
        )
    )
    await session.commit()
    await session.refresh(user)

    https = _is_https(request)
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        key=USER_COOKIE_NAME,
        value=token,
        max_age=settings.user_session_ttl_seconds,
        httponly=True,
        samesite="none" if https else "lax",
        secure=https,
        path="/",
    )
    today_tokens = await get_user_today_tokens(session, user.id)
    storage_quota = await get_user_storage_quota_bytes(session, user, billing)
    return {
        "authenticated": True,
        "is_new_user": is_new_user,
        "token": token,
        "user": serialize_user(
            user,
            today_tokens=today_tokens,
            token_price_per_1k_toman=billing.token_price_per_1k_toman,
            storage_quota_bytes=storage_quota,
            now=now,
        ),
    }


@router.get("/me")
async def get_me(
    response: Response,
    user: User | None = Depends(get_optional_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    if user is None or not user.is_active:
        return {"authenticated": False, "user": None}
    billing = await get_or_init_billing_settings(session)
    today_tokens = await get_user_today_tokens(session, user.id)
    storage_quota = await get_user_storage_quota_bytes(session, user, billing)
    return {
        "authenticated": True,
        "user": serialize_user(
            user,
            today_tokens=today_tokens,
            token_price_per_1k_toman=billing.token_price_per_1k_toman,
            storage_quota_bytes=storage_quota,
        ),
    }


@router.put("/me")
async def update_me(
    body: UpdateProfileBody,
    user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    user.full_name = body.full_name.strip()[:120]
    await session.commit()
    await session.refresh(user)
    billing = await get_or_init_billing_settings(session)
    today_tokens = await get_user_today_tokens(session, user.id)
    storage_quota = await get_user_storage_quota_bytes(session, user, billing)
    return {
        "user": serialize_user(
            user,
            today_tokens=today_tokens,
            token_price_per_1k_toman=billing.token_price_per_1k_toman,
            storage_quota_bytes=storage_quota,
        )
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    token = extract_user_token(request)
    parsed = parse_user_session_token(token)
    if parsed is not None:
        user_id, nonce, _ = parsed
        session_row = await session.scalar(
            select(UserSession).where(
                UserSession.user_id == user_id,
                UserSession.token_nonce == nonce,
                UserSession.revoked_at.is_(None),
            )
        )
        if session_row is not None:
            session_row.revoked_at = datetime.now(timezone.utc)
            await session.commit()

    https = _is_https(request)
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        key=USER_COOKIE_NAME,
        path="/",
        samesite="none" if https else "lax",
        secure=https,
    )
    return {"authenticated": False}
